from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import json
import base64

# =============================================================================
# Google Auth
# =============================================================================

SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']


def get_credentials():
    gsc_base64_key = os.getenv('SEARCH_CONSOLE_KEY')
    if not gsc_base64_key:
        raise ValueError("SEARCH_CONSOLE_KEY environment variable is not set.")
    # Strip whitespace/newlines and fix base64 padding (common with PowerShell encoding)
    key_b64 = gsc_base64_key.strip()
    padding_needed = (4 - len(key_b64) % 4) % 4
    key_b64 += '=' * padding_needed
    decoded_bytes = base64.b64decode(key_b64)
    key_info = json.loads(decoded_bytes.decode('utf-8'))
    credentials = service_account.Credentials.from_service_account_info(key_info, scopes=SCOPES)
    # DWD: impersonate a real Workspace user so clients only need to share with that account
    subject = os.getenv('IMPERSONATE_SUBJECT', '').strip()
    if subject:
        credentials = credentials.with_subject(subject)
    return credentials


def get_service():
    return build('webmasters', 'v3', credentials=get_credentials())


# =============================================================================
# MCP Protocol Request Routing
# =============================================================================

def handle_request(method, params):
    if method == "initialize":
        return handle_initialize()
    elif method == "tools/list":
        return handle_tools_list()
    elif method == "tools/call":
        return handle_tool_call(params)
    else:
        raise ValueError(f"Method not found: {method}")


# =============================================================================
# MCP Protocol Handlers
# =============================================================================

def handle_initialize():
    return {
        "protocolVersion": "2024-11-05",
        "serverInfo": {
            "name": "search_console_mcp",
            "version": "1.0.0"
        },
        "capabilities": {
            "tools": {}
        }
    }


def handle_tools_list():
    return {
        "tools": [
            {
                "name": "list_sites",
                "description": (
                    "List all Google Search Console properties the service account has access to. "
                    "Use this first to discover available client sites and their exact site_url values "
                    "before running queries."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False
                }
            },
            {
                "name": "query_search_analytics",
                "description": (
                    "Query Google Search Console search analytics for a specific property. "
                    "Returns clicks, impressions, CTR, and position data segmented by the specified dimensions. "
                    "Call list_sites first to get valid site_url values."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "site_url": {
                            "type": "string",
                            "description": (
                                "The GSC property URL exactly as returned by list_sites "
                                "(e.g. 'https://example.com/' or 'sc-domain:example.com')."
                            )
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date in YYYY-MM-DD format."
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date in YYYY-MM-DD format."
                        },
                        "dimensions": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["query", "page", "country", "device", "date", "searchAppearance"]
                            },
                            "description": "Dimensions to group results by. Defaults to ['query'].",
                            "default": ["query"]
                        },
                        "row_limit": {
                            "type": "integer",
                            "description": "Maximum rows to return (1-25000). Defaults to 25. For date-trended queries set this to cover the full number of days in the range.",
                            "default": 25,
                            "minimum": 1,
                            "maximum": 25000
                        },
                        "start_row": {
                            "type": "integer",
                            "description": "Zero-based row offset for pagination. Defaults to 0.",
                            "default": 0
                        },
                        "search_type": {
                            "type": "string",
                            "enum": ["web", "image", "video", "news", "discover", "googleNews"],
                            "description": "Search surface to filter by. Defaults to 'web'.",
                            "default": "web"
                        },
                        "aggregation_type": {
                            "type": "string",
                            "enum": ["auto", "byPage", "byProperty"],
                            "description": "How data is aggregated. Defaults to 'auto'.",
                            "default": "auto"
                        },
                        "dimension_filter_groups": {
                            "type": "array",
                            "description": (
                                "Filter groups to narrow results. Filters within a group are combined with AND logic. "
                                "Country values: ISO 3166-1 alpha-3 (e.g. 'GBR', 'USA', 'AUS'). "
                                "Device values: 'DESKTOP', 'MOBILE', 'TABLET'."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "groupType": {
                                        "type": "string",
                                        "enum": ["and"],
                                        "default": "and"
                                    },
                                    "filters": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "dimension": {
                                                    "type": "string",
                                                    "enum": ["query", "page", "country", "device", "searchAppearance"]
                                                },
                                                "operator": {
                                                    "type": "string",
                                                    "enum": ["equals", "notEquals", "contains", "notContains", "includingRegex", "excludingRegex"],
                                                    "default": "equals"
                                                },
                                                "expression": {
                                                    "type": "string",
                                                    "description": "The filter value."
                                                }
                                            },
                                            "required": ["dimension", "expression"]
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "required": ["site_url", "start_date", "end_date"],
                    "additionalProperties": False
                }
            }
        ]
    }


def handle_tool_call(params):
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            return {
                "isError": True,
                "content": [{"type": "text", "text": "Invalid arguments: expected object or JSON string."}]
            }

    if tool_name == "list_sites":
        try:
            result = list_sites()
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": f"Tool error (list_sites): {str(e)}"}]}

    elif tool_name == "query_search_analytics":
        try:
            result = run_search_analytics_query(arguments)
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": f"Tool error (query_search_analytics): {str(e)}"}]}

    else:
        return {"isError": True, "content": [{"type": "text", "text": f"Tool not found: {tool_name}"}]}


# =============================================================================
# Tool Implementations
# =============================================================================

def list_sites():
    """List all GSC properties the service account has access to."""
    service = get_service()
    response = service.sites().list().execute()
    sites = response.get('siteEntry', [])
    return {
        "sites": [
            {
                "site_url": site['siteUrl'],
                "permission_level": site['permissionLevel']
            }
            for site in sites
        ],
        "total": len(sites)
    }


def run_search_analytics_query(arguments):
    """Execute a structured GSC search analytics query."""
    site_url = arguments.get('site_url')
    start_date = arguments.get('start_date')
    end_date = arguments.get('end_date')

    if not site_url or not start_date or not end_date:
        raise ValueError("site_url, start_date, and end_date are required.")

    payload = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": arguments.get('dimensions', ['query']),
        "rowLimit": arguments.get('row_limit', 25),
        "startRow": arguments.get('start_row', 0),
        "type": arguments.get('search_type', 'web'),
        "aggregationType": arguments.get('aggregation_type', 'auto'),
    }

    filter_groups = arguments.get('dimension_filter_groups')
    if filter_groups:
        payload['dimensionFilterGroups'] = filter_groups

    service = get_service()
    response = service.searchanalytics().query(siteUrl=site_url, body=payload).execute()

    rows = response.get('rows', [])
    dimensions = payload['dimensions']

    results = []
    for row in rows:
        data = {}
        keys = row.get('keys', [])
        for i, dim in enumerate(dimensions):
            data[dim] = keys[i] if i < len(keys) else None
        data['clicks'] = row.get('clicks', 0)
        data['impressions'] = row.get('impressions', 0)
        data['ctr'] = round(row.get('ctr', 0) * 100, 4)
        data['position'] = round(row.get('position', 0), 2)
        results.append(data)

    return {
        "site_url": site_url,
        "start_date": start_date,
        "end_date": end_date,
        "dimensions": dimensions,
        "row_count": len(results),
        "rows": results
    }
