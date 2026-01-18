Build the Scenairo:
- URL: `http://127.0.0.1:8000/scenario/build`
- Method: `POST`
- Payload:
```
{
  "base_url": "http://192.168.56.101",
  "start_nodes": true,
  
  "scenario": {
    "gns3_server_ip": "192.168.56.101",
    "project_name": "ae3gis-scenario-builder-test",
    "project_id": "8b26f4d4-5445-4e86-86a0-d46944d8e85b",

    "templates": {
      "test-client": "df206cef-efd5-45dc-93d4-1f94c31cfb16",
      "nginx-server": "65ac4263-d944-4b7d-a068-5a836b29319f"
    },

    "nodes": [
      { "name": "Client-**01", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": -300, "y": -250 },
      { "name": "Client-**02", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": -250, "y": -250 },
      { "name": "Client-**03", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": -200, "y": -250 },
      { "name": "Client-**04", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": -150, "y": -250 },
      { "name": "Client-**05", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": -100, "y": -250 },
      { "name": "Client-**06", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": -50, "y": -250 },
      { "name": "Client-**07", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": 0, "y": -250 },
      { "name": "Client-**08", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": 50, "y": -250 },
      { "name": "Client-**09", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": 100, "y": -250 },
      { "name": "Client-**10", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": 150, "y": -250 },
      { "name": "Client-**11", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": 200, "y": -250 },
      { "name": "Client-**12", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": 250, "y": -250 },
      { "name": "Client-**13", "template_id": "df206cef-efd5-45dc-93d4-1f94c31cfb16", "x": 300, "y": -250 },
			{
				"name": "OpenvSwitch-41",
				"template_id": "e257b341-cec3-4076-a239-181c5101ff37",
				"x": 0,
				"y": -140
			},
			{
				"name": "DHCP-**01",
				"template_id": "3cecbf43-5f8b-4678-97f3-6ace71b02853",
				"x": 0,
				"y": 0
			},
			{
				"name": "Server-**01",
				"template_id": "65ac4263-d944-4b7d-a068-5a836b29319f",
				"x": 300,
				"y": -250
			}
    ],

    "links": [
      { "nodes": [ { "node_id": "Client-**01", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 1, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Client-**02", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 2, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Client-**03", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 3, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Client-**04", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 4, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Client-**05", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 5, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Client-**06", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 6, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Client-**07", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 7, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Client-**08", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 8, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Client-**09", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 9, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Client-**10", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 10, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Client-**11", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 11, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Client-**12", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 12, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Client-**13", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 13, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "Server-**01", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 14, "port_number": 0 } ] },
      { "nodes": [ { "node_id": "DHCP-**01", "adapter_number": 0, "port_number": 0 }, { "node_id": "OpenvSwitch-41", "adapter_number": 15, "port_number": 0 } ] }
    ]
  }
}
```

---

- URL: `http://127.0.0.1:8000/scripts/push`
- Method: `POST`
- Payload: 
**To assign IP and start the web server:**
```
{
  "scripts": [
    {
      "node_name": "Server-**01",
      "local_path": "./run_server.sh",
      "remote_path": "/run_server.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    }
  ],
	"gns3_server_ip": "http://192.168.56.101",
  "concurrency": 5
}
```

**To start the DHCP server:**
```
{
  "scripts": [
    {
      "node_name": "DHCP-**01",
      "local_path": "./run_dhcp.sh",
      "remote_path": "/usr/run_dhcp.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    }
  ],
	"gns3_server_ip": "http://192.168.56.101",
  "concurrency": 5
}
```

**To request IP from DHCP and start benign traffic from client:**
```
{
  "scripts": [
		
    {
      "node_name": "Client-**01",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    },
    {
      "node_name": "Client-**02",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    },
    {
      "node_name": "Client-**03",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    },
    {
      "node_name": "Client-**04",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    },
    {
      "node_name": "Client-**05",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    },
    {
      "node_name": "Client-**06",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    },
    {
      "node_name": "Client-**07",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    },
    {
      "node_name": "Client-**08",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    },
    {
      "node_name": "Client-**09",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    },
    {
      "node_name": "Client-**10",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    },
    {
      "node_name": "Client-**11",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    },
    {
      "node_name": "Client-**12",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    },
    {
      "node_name": "Client-**13",
      "local_path": "./run_http.sh",
      "remote_path": "/usr/run_http.sh",
      "run_after_upload": true,
      "executable": true,
      "overwrite": true,
      "run_timeout": 10,
      "shell": "sh"
    }
  ],
	"gns3_server_ip": "http://192.168.56.101",
  "concurrency": 5
}
```