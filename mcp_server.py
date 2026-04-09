import asyncio
import json
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

app = Server("ai-behaviour-lab")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_audit",
            description="Audit any AI system for safety vulnerabilities. Tests the model against attack families including masking, evasion, prompt injection, and more. Returns a risk score, failures, and recommendations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain to audit. Available: tax, legal",
                        "default": "tax"
                    },
                    "provider": {
                        "type": "string",
                        "description": "Model provider: openai, anthropic, http. Leave empty for simulation mode."
                    },
                    "model": {
                        "type": "string",
                        "description": "Model name e.g. gpt-4o-mini, claude-3-5-sonnet-20240620"
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "System prompt of the AI system being audited"
                    },
                },
                "required": ["domain"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "run_audit":
        raise ValueError(f"Unknown tool: {name}")

    async with httpx.AsyncClient(timeout=300) as client:
        try:
            response = await client.post(
                "http://127.0.0.1:8000/audit",
                json={
                    "domain": arguments.get("domain", "tax"),
                    "provider": None,
                    "model": None,
                    "system_prompt": None,
                }
            )
            response.raise_for_status()
            report = response.json()

            # Format a clean summary for Claude to read
            summary = f"""
AI BEHAVIOUR LAB — AUDIT COMPLETE

Domain: {report['profile']}
Risk Score: {report['risk_score']}/100
Status: {report['status']}
Adapter: {report.get('adapter', 'simulation')}

Top Weakness: {report['top_weakness_family']}
Strongest Area: {report['top_safe_family']}

Family Results:
{chr(10).join(f"  - {k}: avg_lambda={v['avg_lambda']}" for k, v in report['family_summary'].items())}

Failures: {len(report['failures'])}
{chr(10).join(f"  Prompt: {f['input'][:80]}..." for f in report['failures'][:3])}

Recommendations:
{chr(10).join(f"  - {r[:200]}" for r in report.get('recommendations', [])[:3])}
            """.strip()

            return [types.TextContent(type="text", text=summary)]

        except httpx.ConnectError:
            return [types.TextContent(
                type="text",
                text="Could not connect to AI Behaviour Lab API. Make sure the server is running: uvicorn app:app --reload"
            )]
        except Exception as e:
            return [types.TextContent(
                type="text",
                text=f"Audit failed: {str(e)}"
            )]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())