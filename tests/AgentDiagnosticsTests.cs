using System;
using UltronAgent;

class AgentDiagnosticsTests
{
    static void Require(bool condition) { if (!condition) throw new Exception("Diagnostic assertion failed"); }
    static void Main()
    {
        string report = AgentDiagnostics.Evaluate("https://example.invalid", true, "VALID", "Stopped");
        Require(report.Contains("\"url\":\"OK\""));
        Require(report.Contains("\"winrm_native\":\"Stopped\""));
        Require(report.Contains("\"network_checked\":false"));
        Require(report.Contains("\"registration_checked\":false"));
        foreach (string bad in new string[] { "", "http://example.invalid", "https://user:password@example.invalid",
                                              "https://example.invalid/path", "https://example.invalid?token=secret" })
        {
            report = AgentDiagnostics.Evaluate(bad, false, "SERIAL-HOST", "arbitrary-secret");
            Require(report.Contains("HTTPS_ORIGIN_REQUIRED"));
            Require(report.Contains("MISSING_OR_UNREADABLE"));
            Require(report.Contains("REVIEW_REQUIRED"));
            Require(!report.Contains("password") && !report.Contains("arbitrary-secret") && !report.Contains("example.invalid"));
        }
        Console.WriteLine("C# diagnostic evaluator: PASS (no files, network or services accessed)");
    }
}
