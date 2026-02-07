"""Service for deploying syslog collectors and injecting logging commands."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, MutableMapping

from core.gns3_client import GNS3Client, GNS3APIError
from core.telnet_client import TelnetSettings, TelnetConsole
from core.nodes import resolve_console_target
from models.submissions import SnitchNodeInfo

logger = logging.getLogger(__name__)


@dataclass
class CollectorConfig:
    """Configuration for a single syslog collector."""
    
    name_suffix: str  # e.g., "IT-Collector"
    switch_name: str  # e.g., "IT-Switch"


@dataclass
class LogCollectorResult:
    """Result of log collection setup."""
    
    snitch_nodes: list[SnitchNodeInfo]
    injected_nodes: list[str]
    skipped_nodes: list[str]
    errors: list[str]
    reused_existing: bool = False


class LogCollector:
    """Service for managing syslog collectors in GNS3 projects."""

    def __init__(
        self,
        client: GNS3Client,
        project_id: str,
        gns3_server_ip: str,
        syslog_template_name: str = "syslog-collector",
    ):
        self.client = client
        self.project_id = project_id
        self.gns3_server_ip = gns3_server_ip
        self.syslog_template_name = syslog_template_name

    def _find_template_id(self) -> str:
        """Find the syslog-collector template ID."""
        for template in self.client.list_templates():
            if template.get("name") == self.syslog_template_name:
                return template["template_id"]
        raise LookupError(f"Template '{self.syslog_template_name}' not found on GNS3 server")

    def _find_node_by_name(self, name: str) -> MutableMapping[str, Any] | None:
        """Find a node by name in the project."""
        nodes = self.client.list_nodes(self.project_id)
        for node in nodes:
            if node.get("name") == name:
                return node
        return None

    def _find_switch(self, switch_name: str) -> MutableMapping[str, Any]:
        """Find a switch node by name."""
        node = self._find_node_by_name(switch_name)
        if node is None:
            raise LookupError(f"Switch '{switch_name}' not found in project")
        return node

    def _find_available_port(self, node: MutableMapping[str, Any]) -> tuple[int, int]:
        """Find an available port on a switch node.
        
        Returns (adapter_number, port_number).
        
        For Open vSwitch, each port is a separate adapter with port_number=0:
        - Port 0 = adapter 0, port 0
        - Port 1 = adapter 1, port 0
        - Port 15 = adapter 15, port 0
        
        Searches from adapter 15 down to avoid conflicts with existing scenario links.
        """
        # Get all links in the project
        links = self.client.list_project_links(self.project_id)
        node_id = node["node_id"]
        
        # Find which adapters are already in use
        used_adapters: set[int] = set()
        for link in links:
            for endpoint in link.get("nodes", []):
                if endpoint.get("node_id") == node_id:
                    adapter = endpoint.get("adapter_number", 0)
                    used_adapters.add(adapter)
        
        # Find an available adapter starting from 15 (last port) to avoid conflicts
        # For Open vSwitch, each adapter is a port with port_number=0
        # IMPORTANT: Skip adapter 0 (first adapter) as it can cause DHCP/connectivity issues
        for adapter_num in range(15, 0, -1):  # 15 down to 1 (skip adapter 0)
            if adapter_num not in used_adapters:
                logger.debug(f"Selected adapter {adapter_num} on {node.get('name')} (avoiding adapter 0)")
                return adapter_num, 0  # adapter_number, port_number=0 for switches
        
        raise RuntimeError(f"No available ports on node '{node.get('name')}' (adapters 1-15 all in use)")

    async def _ensure_syslog_running(
        self,
        node: MutableMapping[str, Any],
    ) -> bool:
        """Ensure syslog-ng is running on a collector node.
        
        Always starts syslog-ng first (idempotent), then verifies it's running.
        Returns True if syslog-ng is running, False otherwise.
        """
        console_target = resolve_console_target(node, self.gns3_server_ip)
        if not console_target:
            logger.warning(f"No console target for node {node.get('name')}")
            return False
        
        host, port = console_target
        settings = TelnetSettings(host=host, port=port)
        
        try:
            async with TelnetConsole(settings) as console:
                await asyncio.sleep(0.5)
                await console.read(timeout=1.0)  # Clear buffer
                
                # Always start syslog-ng first (it's idempotent - won't start a second instance)
                logger.info(f"Starting syslog-ng on {node.get('name')}...")
                await console.run_command("syslog-ng", read_duration=2.0)
                
                # Wait for it to initialize
                await asyncio.sleep(1.5)
                
                # Verify it's running
                output = await console.run_command("pgrep syslog-ng", read_duration=2.0)
                
                if output.strip() and any(c.isdigit() for c in output):
                    logger.info(f"syslog-ng running on {node.get('name')} (PID: {output.strip()})") 
                    return True
                
                # Try starting again if first attempt failed
                logger.warning(f"syslog-ng not running after first attempt on {node.get('name')}, retrying...")
                await console.run_command("syslog-ng", read_duration=2.0)
                await asyncio.sleep(1.5)
                
                output = await console.run_command("pgrep syslog-ng", read_duration=2.0)
                if output.strip() and any(c.isdigit() for c in output):
                    logger.info(f"syslog-ng started on retry on {node.get('name')} (PID: {output.strip()})")
                    return True
                
                logger.error(f"Failed to start syslog-ng on {node.get('name')} after 2 attempts")
                return False
                    
        except Exception as e:
            logger.error(f"Failed to ensure syslog-ng running on {node.get('name')}: {e}")
            return False

    async def _get_node_ip_address(
        self,
        node: MutableMapping[str, Any],
    ) -> str | None:
        """Get the IP address of a node via telnet.
        
        First checks if an IP is already assigned (via DHCP or static).
        If no IP found, attempts to request one via dhclient.
        
        Returns the IP address or None if unable to obtain one.
        """
        console_target = resolve_console_target(node, self.gns3_server_ip)
        if not console_target:
            logger.warning(f"No console target for node {node.get('name')}")
            return None
        
        host, port = console_target
        settings = TelnetSettings(host=host, port=port)
        
        try:
            async with TelnetConsole(settings) as console:
                # Wait for the container to be ready
                await asyncio.sleep(1)
                
                # Clear any pending output
                await console.read(timeout=1.0)
                
                # Check if IP is already assigned using hostname -I
                output = await console.run_command("hostname -I", read_duration=2.0)
                ip_address = self._parse_ip_from_output(output)
                
                if ip_address:
                    logger.info(f"Found existing IP {ip_address} on {node.get('name')}")
                    return ip_address
                
                # No IP found, try to request one via DHCP client
                logger.info(f"No IP found on {node.get('name')}, requesting via DHCP...")
                await console.run_command("dhclient -v -1", read_duration=10.0)
                
                # Wait a moment for DHCP to complete
                await asyncio.sleep(2)
                
                # Check again for IP
                output = await console.run_command("hostname -I", read_duration=2.0)
                ip_address = self._parse_ip_from_output(output)
                
                if ip_address:
                    logger.info(f"Obtained IP {ip_address} via DHCP on {node.get('name')}")
                    return ip_address
                
                logger.error(f"Failed to obtain IP for {node.get('name')} - no DHCP server or static IP")
                return None
                    
        except Exception as e:
            logger.error(f"Failed to get IP for {node.get('name')}: {e}")
            return None
    
    def _parse_ip_from_output(self, output: str) -> str | None:
        """Parse IP address from hostname -I output.
        
        hostname -I returns space-separated list of IPs, e.g., "192.168.0.50 "
        We take the first non-empty, non-localhost IP.
        """
        import re
        
        # Clean the output
        clean_output = output.strip()
        
        # Find all IPv4 addresses in the output
        ip_pattern = r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
        matches = re.findall(ip_pattern, clean_output)
        
        for ip in matches:
            # Skip localhost and link-local addresses
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
        
        return None

    def _create_collector_node(
        self,
        student_name: str,
        collector_config: CollectorConfig,
        template_id: str,
    ) -> tuple[MutableMapping[str, Any], bool]:
        """Create a collector node or return existing one.
        
        Returns (node, reused).
        """
        node_name = f"{student_name}-{collector_config.name_suffix}"
        
        # Check if node already exists
        existing = self._find_node_by_name(node_name)
        if existing:
            logger.info(f"Reusing existing collector node: {node_name}")
            return existing, True
        
        # Find the switch to get position reference
        switch = self._find_switch(collector_config.switch_name)
        
        # Position the collector near the switch
        x = switch.get("x", 0) + 150
        y = switch.get("y", 0) + 100
        
        # Create the node
        node = self.client.add_node_from_template(
            self.project_id,
            template_id,
            node_name,
            x, y
        )
        logger.info(f"Created collector node: {node_name}")
        return node, False

    def _connect_to_switch(
        self,
        collector_node: MutableMapping[str, Any],
        switch_name: str,
    ) -> bool:
        """Connect a collector node to a switch."""
        switch = self._find_switch(switch_name)
        
        try:
            # Find available port on switch
            adapter, port = self._find_available_port(switch)
            
            # Create link
            # Collector uses adapter 0, port 0 (eth0)
            link_payload_a = {
                "node_id": collector_node["node_id"],
                "adapter_number": 0,
                "port_number": 0,
            }
            link_payload_b = {
                "node_id": switch["node_id"],
                "adapter_number": adapter,
                "port_number": port,
            }
            
            self.client.create_link(self.project_id, link_payload_a, link_payload_b)
            logger.info(f"Connected {collector_node.get('name')} to {switch_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect {collector_node.get('name')} to {switch_name}: {e}")
            return False

    async def _setup_single_collector(
        self,
        student_name: str,
        config: CollectorConfig,
        template_id: str,
    ) -> tuple[SnitchNodeInfo | None, list[str], bool]:
        """Setup a single collector node.
        
        Returns (snitch_info, errors, reused).
        """
        errors: list[str] = []
        reused = False
        
        try:
            # Create or reuse collector node
            node, reused = self._create_collector_node(student_name, config, template_id)
            
            # Connect to switch (skip if already connected)
            if not reused:
                self._connect_to_switch(node, config.switch_name)
            
            # Refresh node data to get console info
            node = self.client.get_node(self.project_id, node["node_id"])
            
            # Start the node
            self.client.start_node(self.project_id, node["node_id"])
            
            # Wait for boot
            await asyncio.sleep(3)
            
            # Get IP address (via DHCP or already assigned)
            ip_address = await self._get_node_ip_address(node)
            
            if not ip_address:
                error_msg = f"Failed to obtain IP for {config.name_suffix} - ensure DHCP server is running or assign static IP"
                logger.error(error_msg)
                errors.append(error_msg)
                return None, errors, reused
            
            # Ensure syslog-ng is running on the collector
            syslog_running = await self._ensure_syslog_running(node)
            if not syslog_running:
                error_msg = f"Warning: syslog-ng may not be running on {config.name_suffix}"
                logger.warning(error_msg)
                errors.append(error_msg)
                # Continue anyway - it might still work
            
            snitch_info = SnitchNodeInfo(
                node_id=node["node_id"],
                name=node["name"],
                ip_address=ip_address,
                port=514,
                connected_to_switch=config.switch_name,
                console_port=node.get("console"),
                console_host=node.get("console_host") or self.gns3_server_ip,
            )
            return snitch_info, errors, reused
            
        except Exception as e:
            error_msg = f"Failed to setup {config.name_suffix}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)
            return None, errors, reused

    async def setup_collectors(
        self,
        student_name: str,
        collectors: list[CollectorConfig],
    ) -> tuple[list[SnitchNodeInfo], list[str], bool]:
        """Deploy and configure syslog collector nodes concurrently.
        
        Returns (snitch_nodes, errors, reused_existing).
        """
        template_id = self._find_template_id()
        
        # Setup all collectors in parallel
        tasks = [
            self._setup_single_collector(student_name, config, template_id)
            for config in collectors
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        snitch_nodes: list[SnitchNodeInfo] = []
        errors: list[str] = []
        any_reused = False
        
        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
            else:
                snitch_info, collector_errors, reused = result
                errors.extend(collector_errors)
                if reused:
                    any_reused = True
                if snitch_info:
                    snitch_nodes.append(snitch_info)
        
        return snitch_nodes, errors, any_reused

    def _get_eligible_nodes(self) -> tuple[list[MutableMapping[str, Any]], list[str]]:
        """Get nodes eligible for PROMPT_COMMAND injection.
        
        Filters out:
        - Nodes without telnet console
        - Switches (name contains 'Switch')
        - Collectors (name contains 'Collector')
        
        Returns (eligible_nodes, skipped_node_names).
        """
        nodes = self.client.list_nodes(self.project_id)
        eligible: list[MutableMapping[str, Any]] = []
        skipped: list[str] = []
        
        for node in nodes:
            name = node.get("name", "")
            console_type = node.get("console_type", "")
            
            # Skip non-telnet nodes
            if console_type != "telnet":
                skipped.append(f"{name} (console_type={console_type})")
                continue
            
            # Skip switches and collectors
            if "Switch" in name or "Collector" in name:
                skipped.append(f"{name} (infrastructure node)")
                continue
            
            eligible.append(node)
        
        return eligible, skipped

    def _determine_collector_ip(
        self,
        node: MutableMapping[str, Any],
        snitch_nodes: list[SnitchNodeInfo],
    ) -> str:
        """Determine which collector IP a node should send logs to.
        
        Uses layer field if available, otherwise checks name for IT/OT.
        Defaults to the first collector if ambiguous.
        """
        if not snitch_nodes:
            raise ValueError("No snitch nodes available")
        
        name = node.get("name", "").upper()
        
        # Check for OT indicators (higher priority since IT is default)
        if "OT" in name:
            # Find OT collector
            for snitch in snitch_nodes:
                if "OT" in snitch.name.upper():
                    return snitch.ip_address
        
        # Default to IT collector (or first available)
        for snitch in snitch_nodes:
            if "IT" in snitch.name.upper():
                return snitch.ip_address
        
        # Fallback to first collector
        return snitch_nodes[0].ip_address

    async def inject_prompt_command(
        self,
        snitch_nodes: list[SnitchNodeInfo],
    ) -> tuple[list[str], list[str], list[str]]:
        """Inject PROMPT_COMMAND into all eligible nodes concurrently.
        
        Returns (injected_nodes, skipped_nodes, errors).
        """
        eligible_nodes, skipped = self._get_eligible_nodes()
        
        # Semaphore to limit concurrent connections
        semaphore = asyncio.Semaphore(8)
        
        async def inject_single_node(node: MutableMapping[str, Any]) -> tuple[str | None, str | None]:
            """Inject into a single node. Returns (node_name, error) or (node_name, None) on success."""
            name = node.get("name", "Unknown")
            
            async with semaphore:
                try:
                    console_target = resolve_console_target(node, self.gns3_server_ip)
                    if not console_target:
                        return None, f"{name} (no console)"
                    
                    host, port = console_target
                    collector_ip = self._determine_collector_ip(node, snitch_nodes)
                    
                    # Build the PROMPT_COMMAND
                    prompt_cmd = f"export PROMPT_COMMAND='history -a >(tee -a ~/.bash_history | logger -n {collector_ip} -P 514 -t \"Student-CMD\")'"
                    
                    settings = TelnetSettings(host=host, port=port)
                    
                    async with TelnetConsole(settings) as console:
                        # Wait briefly for connection
                        await asyncio.sleep(0.5)
                        await console.read(timeout=1.0)  # Clear buffer
                        
                        # Send the command
                        await console.run_command(prompt_cmd, read_duration=2.0)
                        
                        # Also add to bashrc for persistence
                        bashrc_cmd = f"echo \"{prompt_cmd}\" >> ~/.bashrc"
                        await console.run_command(bashrc_cmd, read_duration=2.0)
                        
                        logger.info(f"Injected PROMPT_COMMAND into {name} -> {collector_ip}")
                        return name, None
                        
                except Exception as e:
                    error_msg = f"Failed to inject into {name}: {e}"
                    logger.error(error_msg)
                    return None, error_msg
        
        # Run all injections concurrently
        tasks = [inject_single_node(node) for node in eligible_nodes]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        injected: list[str] = []
        errors: list[str] = []
        
        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
            else:
                node_name, error = result
                if node_name:
                    injected.append(node_name)
                if error:
                    if "(no console)" in error:
                        skipped.append(error)
                    else:
                        errors.append(error)
        
        return injected, skipped, errors

    async def retrieve_logs(
        self,
        snitch_node: SnitchNodeInfo,
    ) -> str:
        """Retrieve logs from a snitch collector node via telnet.
        
        Gets fresh node info from GNS3 to ensure correct console port,
        ensures syslog-ng is running, then reads the log file.
        """
        # Get fresh node info from GNS3 (console port may have changed)
        node = self.client.get_node(self.project_id, snitch_node.node_id)
        if not node:
            raise ValueError(f"Node {snitch_node.name} not found in project")
        
        # Ensure the node is started
        node_status = node.get("status", "stopped")
        if node_status != "started":
            logger.info(f"Starting {snitch_node.name} (was {node_status})...")
            self.client.start_node(self.project_id, snitch_node.node_id)
            await asyncio.sleep(2)  # Wait for node to start
            node = self.client.get_node(self.project_id, snitch_node.node_id)
        
        # Get console target from fresh node info
        console_target = resolve_console_target(node, self.gns3_server_ip)
        if not console_target:
            raise ValueError(f"No console available for {snitch_node.name}")
        
        host, port = console_target
        
        # Ensure syslog-ng is running before reading logs
        await self._ensure_syslog_running(node)
        
        settings = TelnetSettings(host=host, port=port)
        
        try:
            async with TelnetConsole(settings) as console:
                # Wait for connection
                await asyncio.sleep(0.5)
                await console.read(timeout=1.0)  # Clear buffer
                
                # Read the log file
                output = await console.run_command("cat /var/log/student.log", read_duration=5.0)
                
                # Clean up the output (remove command echo and prompt)
                lines = output.split("\n")
                # Filter out lines containing the command itself or prompts
                clean_lines = [
                    line for line in lines
                    if not line.strip().startswith("cat ") and
                       not line.strip().startswith("#") and
                       not line.strip().startswith("/ #")
                ]
                
                return "\n".join(clean_lines).strip()
                
        except Exception as e:
            logger.error(f"Failed to retrieve logs from {snitch_node.name}: {e}")
            raise

    def delete_collector_nodes(self, student_name: str) -> list[str]:
        """Delete all collector nodes for a student.
        
        Returns list of deleted node names.
        """
        deleted = []
        nodes = self.client.list_nodes(self.project_id)
        
        for node in nodes:
            name = node.get("name", "")
            # Match nodes that start with student name and end with Collector
            if name.startswith(f"{student_name}-") and "Collector" in name:
                try:
                    self.client.delete_node(self.project_id, node["node_id"])
                    deleted.append(name)
                    logger.info(f"Deleted collector node: {name}")
                except Exception as e:
                    logger.error(f"Failed to delete {name}: {e}")
        
        return deleted


async def setup_logging_for_student(
    client: GNS3Client,
    project_id: str,
    gns3_server_ip: str,
    student_name: str,
    it_switch_name: str = "IT-Switch",
    ot_switch_name: str = "OT-Switch",
    syslog_template_name: str = "syslog-collector",
) -> LogCollectorResult:
    """High-level function to set up logging for a student.
    
    Creates collector nodes, obtains IPs via DHCP, and injects PROMPT_COMMAND.
    The DHCP server must be running before calling this function.
    """
    collector = LogCollector(client, project_id, gns3_server_ip, syslog_template_name)
    
    # Define collector configurations
    collectors = [
        CollectorConfig(
            name_suffix="IT-Collector",
            switch_name=it_switch_name,
        ),
        CollectorConfig(
            name_suffix="OT-Collector",
            switch_name=ot_switch_name,
        ),
    ]
    
    # Setup collectors
    snitch_nodes, setup_errors, reused = await collector.setup_collectors(student_name, collectors)
    
    if not snitch_nodes:
        return LogCollectorResult(
            snitch_nodes=[],
            injected_nodes=[],
            skipped_nodes=[],
            errors=setup_errors or ["No collectors could be deployed. Ensure DHCP server is running or assign static IPs."],
            reused_existing=reused,
        )
    
    # Inject PROMPT_COMMAND into nodes
    injected, skipped, inject_errors = await collector.inject_prompt_command(snitch_nodes)
    
    return LogCollectorResult(
        snitch_nodes=snitch_nodes,
        injected_nodes=injected,
        skipped_nodes=skipped,
        errors=setup_errors + inject_errors,
        reused_existing=reused,
    )


async def retrieve_all_logs(
    client: GNS3Client,
    project_id: str,
    gns3_server_ip: str,
    snitch_nodes: list[SnitchNodeInfo],
) -> tuple[dict[str, str], list[str]]:
    """Retrieve logs from all snitch nodes concurrently.
    
    Returns tuple of (logs_dict, errors).
    logs_dict maps collector type (e.g., 'it', 'ot') to log content.
    errors contains any retrieval errors that occurred.
    """
    collector = LogCollector(client, project_id, gns3_server_ip)
    
    async def retrieve_single(snitch: SnitchNodeInfo) -> tuple[str, str, str | None]:
        """Retrieve logs from a single snitch. Returns (collector_type, logs, error)."""
        collector_type = "it" if "IT" in snitch.name.upper() else "ot" if "OT" in snitch.name.upper() else snitch.name.lower()
        
        try:
            log_content = await collector.retrieve_logs(snitch)
            
            # Log empty results as a warning
            if not log_content or not log_content.strip():
                warning = f"{snitch.name}: Log file is empty - commands may not be reaching the collector"
                logger.warning(warning)
                return collector_type, "", warning
            
            return collector_type, log_content, None
                
        except Exception as e:
            error_msg = f"Failed to retrieve logs from {snitch.name}: {e}"
            logger.error(error_msg)
            return collector_type, "", error_msg
    
    # Retrieve logs from all collectors in parallel
    tasks = [retrieve_single(snitch) for snitch in snitch_nodes]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    logs: dict[str, str] = {}
    errors: list[str] = []
    
    for result in results:
        if isinstance(result, Exception):
            errors.append(str(result))
        else:
            collector_type, log_content, error = result
            logs[collector_type] = log_content
            if error:
                errors.append(error)
    
    return logs, errors


def teardown_logging_for_student(
    client: GNS3Client,
    project_id: str,
    gns3_server_ip: str,
    student_name: str,
) -> list[str]:
    """Remove all collector nodes for a student."""
    collector = LogCollector(client, project_id, gns3_server_ip)
    return collector.delete_collector_nodes(student_name)
