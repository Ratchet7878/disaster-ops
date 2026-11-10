"""Verifies the OpenAI-compatible adapter against a local stub server (no network, no cost)."""
import json, os, sys, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import seed_gsi
from app.agent import llm_client, orchestrator

SEEN = []

class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append(body)
        has_tool_result = any(m["role"] == "tool" for m in body["messages"])
        if has_tool_result:
            msg = {"role": "assistant", "content": "Done: see tool result."}
        else:
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "find_shelter_or_need", "arguments": json.dumps({"query": "Shelter A water"})}}]}
        out = json.dumps({"choices": [{"message": msg}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

class TestAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        seed_gsi.run_default_seed(reset=True)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_full_tool_loop_over_openai_format(self):
        os.environ["LLM_PROVIDER"] = "openai"
        os.environ["LLM_BASE_URL"] = f"http://127.0.0.1:{self.srv.server_port}/v1"
        r = orchestrator.run_agent("Shelter A needs water")
        self.assertNotIn("error", r)
        self.assertEqual(r["final_message"], "Done: see tool result.")
        calls = [t for t in r["trace"] if t["type"] == "tool_call"]
        self.assertEqual(calls[0]["name"], "find_shelter_or_need")
        res = [t for t in r["trace"] if t["type"] == "tool_result"][0]["result"]
        self.assertTrue(res["found"])
        self.assertEqual(res["matches"][0]["shelter_id"], "SHELTER_A")
        self.assertEqual(SEEN[0]["messages"][0]["role"], "system")
        self.assertEqual(SEEN[0]["tools"][0]["type"], "function")

    def test_provider_inference_and_config_errors(self):
        for k in ("LLM_PROVIDER", "ANTHROPIC_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            os.environ.pop(k, None)
        self.assertEqual(llm_client.provider(), "ollama")
        os.environ["GROQ_API_KEY"] = "x"
        self.assertEqual(llm_client.provider(), "groq")
        os.environ.pop("GROQ_API_KEY")
        os.environ["LLM_PROVIDER"] = "anthropic"
        with self.assertRaises(llm_client.LlmConfigError):
            llm_client.call_claude([{"role": "user", "content": "hi"}])
        os.environ.pop("LLM_PROVIDER")

if __name__ == "__main__":
    unittest.main()
