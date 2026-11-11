using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Management;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Reflection;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Threading;
using Microsoft.Win32;

namespace UltronAgent
{
    // =========================================================================
    // SERVIÇO WINDOWS NATIVO (UltronService)
    // =========================================================================
    public class UltronWindowsService : ServiceBase
    {
        private Thread _workerThread;
        private bool _stopping = false;

        public UltronWindowsService()
        {
            this.ServiceName = "UltronService";
            this.CanStop = true;
            this.CanShutdown = true;
            this.AutoLog = true;
        }

        protected override void OnStart(string[] args)
        {
            _stopping = false;
            _workerThread = new Thread(WorkerLoop)
            {
                IsBackground = true,
                Name = "UltronAgentWorker"
            };
            _workerThread.Start();
        }

        protected override void OnStop()
        {
            _stopping = true;
            if (_workerThread != null && _workerThread.IsAlive)
            {
                _workerThread.Join(3000);
            }
        }

        private void WorkerLoop()
        {
            Program.RunAutonomousEngine(ref _stopping);
        }
    }

    // =========================================================================
    // PROGRAMA PRINCIPAL
    // =========================================================================
    
    public static class Logger
    {
        private static string logPath = @"C:\ProgramData\Ultron\agent.log";

        static Logger()
        {
            try
            {
                if (!Directory.Exists(@"C:\ProgramData\Ultron"))
                    Directory.CreateDirectory(@"C:\ProgramData\Ultron");
            } catch {}
        }

        public static void Info(string msg, ConsoleColor color = ConsoleColor.Gray)
        {
            WriteLog("INFO", msg);
            if (Environment.UserInteractive && !Program.DaemonMode && !Program.SilentMode)
            {
                try
                {
                    Console.ForegroundColor = color;
                    Console.WriteLine(msg);
                    Console.ResetColor();
                } catch {}
            }
        }

        public static void Error(string msg)
        {
            WriteLog("ERROR", msg);
            if (Environment.UserInteractive && !Program.DaemonMode && !Program.SilentMode)
            {
                try
                {
                    Console.ForegroundColor = ConsoleColor.Red;
                    Console.WriteLine(msg);
                    Console.ResetColor();
                } catch {}
            }
        }

        private static void WriteLog(string level, string msg)
        {
            try
            {
                string line = string.Format("{0:yyyy-MM-dd HH:mm:ss} [{1}] {2}{3}", DateTime.Now, level, msg, Environment.NewLine);
                File.AppendAllText(logPath, line);
            } catch {}
        }
    }

    class Program
    {
        public const string CurrentVersion = "2.3.0";
        public static string ServerUrl = "";
        public static string ClientId = "cliente_padrao";
        public static bool SilentMode = false;
        public static bool DaemonMode = false;

        private static string _lastReportedIp = "";
        private static HashSet<string> _reportedBsods = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        static void Main(string[] args)
        {
            AppDomain.CurrentDomain.UnhandledException += (sender, e) => {
                Logger.Error("Fatal Unhandled Exception: " + e.ExceptionObject.ToString());
            };
            
            if (Environment.UserInteractive) {
                try { Console.OutputEncoding = Encoding.UTF8; } catch { }
            }

            string configPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "Ultron", "server.url");
            if (File.Exists(configPath)) ServerUrl = File.ReadAllText(configPath).Trim().TrimEnd('/');
            ParseArguments(args);
            Uri configured;
            if (!Uri.TryCreate(ServerUrl, UriKind.Absolute, out configured) ||
                configured.Scheme != Uri.UriSchemeHttps || configured.UserInfo.Length != 0 ||
                configured.AbsolutePath != "/" || configured.Query.Length != 0 || configured.Fragment.Length != 0)
            {
                Console.Error.WriteLine("Configure HTTPS em ProgramData/Ultron/server.url ou --server.");
                Environment.ExitCode = 2;
                return;
            }

            // 1. Execução no modo Windows Service
            if (args.Length > 0 && (args[0].Equals("--service", StringComparison.OrdinalIgnoreCase) || args[0].Equals("/service", StringComparison.OrdinalIgnoreCase)))
            {
                ServiceBase.Run(new UltronWindowsService());
                return;
            }

            // 2. Comandos administrativos que exigem privilégios elevados
            if (args.Length > 0 && (args[0] == "--uninstall" || args[0] == "-u" || args[0] == "--cleanup" || args[0] == "--limpar") && !IsAdministrator())
            {
                if (!SilentMode)
                {
                    Logger.Info("[!] Solicitando privilégios de Administrador para liberar o sistema...", ConsoleColor.Yellow);
                }
                RestartAsAdmin(args);
                return;
            }

            // 3. Modos de Instalação e Limpeza
            if (args.Length > 0)
            {
                string cmd = args[0].ToLower();
                if (cmd == "--install-service" || cmd == "-i" || cmd == "--install")
                {
                    InstallWindowsService();
                    return;
                }
                if (cmd == "--uninstall" || cmd == "-u" || cmd == "--cleanup" || cmd == "--limpar")
                {
                    UninstallAndCleanSystem();
                    return;
                }
            }

            PrintBanner();

            // 4. Executa liberações de Sistema e Rede (WinRM, Firewall, UAC, UltronAdmin)
            UnlockSystem();

            // 5. Coleta telemetria e registra no Ultron Server
            string telemetryJson = CollectTelemetryJson();
            RegisterAtServer(telemetryJson);

            // 6. Instalação automática do serviço para operação contínua
            if (!DaemonMode)
            {
                InstallWindowsServiceSilently();
            }

            // 7. Loop de execução
            if (DaemonMode)
            {
                bool stopFlag = false;
                RunAutonomousEngine(ref stopFlag);
            }
            else
            {
                if (!SilentMode)
                {
                    try
                    {
                        Console.ForegroundColor = ConsoleColor.Green;
                        Console.WriteLine("\n[INFO] Tentativa de registro concluida; confira a confirmacao acima.");
                        Console.WriteLine("[INFO] Use --install-service para instalacao explicita.");
                        Console.WriteLine("[INFO] Registro e WinRM exigem verificacao independente.");
                        Console.ResetColor();
                        Console.WriteLine("\nPressione qualquer tecla para fechar esta janela...");
                        if (!Console.IsInputRedirected)
                        {
                            Console.ReadKey();
                        }
                    }
                    catch { }
                }
            }
        }

        static void ParseArguments(string[] args)
        {
            for (int i = 0; i < args.Length; i++)
            {
                string arg = args[i].ToLower();
                if (arg == "--server" && i + 1 < args.Length)
                {
                    ServerUrl = args[i + 1].TrimEnd('/');
                    i++;
                }
                else if (arg == "--client" && i + 1 < args.Length)
                {
                    ClientId = args[i + 1];
                    i++;
                }
                else if (arg == "--silent" || arg == "-s")
                {
                    SilentMode = true;
                }
                else if (arg == "--daemon" || arg == "-d" || arg == "--background")
                {
                    DaemonMode = true;
                }
            }
        }

        static bool IsAdministrator()
        {
            try
            {
                WindowsIdentity identity = WindowsIdentity.GetCurrent();
                WindowsPrincipal principal = new WindowsPrincipal(identity);
                return principal.IsInRole(WindowsBuiltInRole.Administrator);
            }
            catch { return false; }
        }

        static void RestartAsAdmin(string[] args)
        {
            try
            {
                ProcessStartInfo proc = new ProcessStartInfo();
                proc.UseShellExecute = true;
                proc.WorkingDirectory = Environment.CurrentDirectory;
                proc.FileName = Process.GetCurrentProcess().MainModule.FileName;
                proc.Arguments = string.Join(" ", args);
                proc.Verb = "runas";
                Process.Start(proc);
            }
            catch (Exception ex)
            {
                Logger.Error("[-] Falha ao obter privilégios de Administrador: " + ex.Message);
            }
        }

        static void PrintBanner()
        {
            if (SilentMode) return;
            try
            {
                Logger.Info(@"===============================================================
       [ULTRON] LAB AUTOMATION AUTONOMOUS AGENT v2.3.0        
       Pense Rede Network Solutions - Laboratorio de TI        
===============================================================", ConsoleColor.Cyan);
            } catch { }
        }

        static void Log(string msg, ConsoleColor color)
        {
            Logger.Info(msg, color);
        }

        // =====================================================================
        // DESBLOQUEIO E AUTO-CURA DO SISTEMA
        // =====================================================================
        public static void UnlockSystem()
        {
            Log("[INFO] WinRM nativo deve ser provisionado separadamente pela equipe. Nenhuma politica foi alterada.", ConsoleColor.Yellow);
        }

        // =====================================================================
        // GERENCIAMENTO DO SERVIÇO WINDOWS
        // =====================================================================
        public static void InstallWindowsService()
        {
            Logger.Error("Use agent/Install-Agent.ps1 -WhatIf para revisar e depois instalar explicitamente.");
            Environment.ExitCode = 2;
        }

        public static void InstallWindowsServiceSilently()
        {
            // Compatibilidade de API: instalacao exige --install-service explicito.
        }

        public static void UninstallAndCleanSystem()
        {
            Log("[*] Iniciando processo de limpeza e desinstalação do Ultron...", ConsoleColor.Yellow);
            try
            {
                // 1. Para e deleta o serviço do Windows
                RunCommand("cmd.exe", "/c sc stop UltronService & net stop UltronService");
                RunCommand("cmd.exe", "/c sc delete UltronService");
                Log("    [OK] Serviço UltronService removido.", ConsoleColor.Green);

                // 2. Remove regras de Firewall
                RunCommand("netsh.exe", "advfirewall firewall delete rule name=\"Ultron WinRM 5985\"");
                RunCommand("netsh.exe", "advfirewall firewall delete rule name=\"Ultron SMB 445\"");
                RunCommand("netsh.exe", "advfirewall firewall delete rule name=\"Ultron RPC 135\"");
                RunCommand("netsh.exe", "advfirewall firewall delete rule name=\"Ultron RDP 3389\"");

                // 3. Remove usuário UltronAdmin/penserede (opicional, deixamos para cleanup manual ou chatops)
                // Contas preexistentes pertencem ao administrador; nao excluir.
                Log("    [INFO] Contas Windows preservadas.", ConsoleColor.Gray);

                // 4. Agenda remoção da pasta Program Files e auto-exclusão
                string targetDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "UltronAgent");
                string batCleaner = Path.Combine(Path.GetTempPath(), "ultron_cleanup.bat");
                File.WriteAllText(batCleaner, string.Format(
                    "@echo off\r\nping 127.0.0.1 -n 3 >nul\r\nrmdir /s /q \"{0}\"\r\ndel \"%~f0\"\r\n",
                    targetDir
                ));
                Process.Start(new ProcessStartInfo("cmd.exe", "/c \"" + batCleaner + "\"") { CreateNoWindow = true, UseShellExecute = false });

                Log("\n🎉 Limpeza concluída! A máquina está pronta para entrega ao cliente.", ConsoleColor.Cyan);
            }
            catch (Exception ex)
            {
                Log("[!] Erro durante a limpeza: " + ex.Message, ConsoleColor.Red);
            }
        }

        // =====================================================================
        // ENGINE AUTÔNOMA DE SEGUNDO PLANO (WATCHDOG, REVERSE POLLER, BSOD, OTA)
        // =====================================================================
        public static void RunAutonomousEngine(ref bool stopping)
        {
            int cycleCount = 0;
            _lastReportedIp = GetLocalIPAddress();

            while (!stopping)
            {
                try
                {
                    cycleCount++;

                    // 1. WATCHDOG DE AUTO-CURA (A cada 20 segundos)
                    try
                    {
                        EnsureWinRMRunning();
                        string currentIp = GetLocalIPAddress();
                        if (currentIp != _lastReportedIp && currentIp != "127.0.0.1")
                        {
                            _lastReportedIp = currentIp;
                            string freshTele = CollectTelemetryJson();
                            RegisterAtServer(freshTele);
                        }
                    }
                    catch { }

                    // 2. REVERSE TASK POLLER (Consulta se há tarefas na fila do Ultron)
                    try
                    {
                        PollAndExecuteTasks();
                    }
                    catch { }

                    // 3. BSOD & HARDWARE HEALTH WATCHDOG (A cada ~60 segundos)
                    if (cycleCount % 3 == 0)
                    {
                        try
                        {
                            CheckForNewBsods();
                        }
                        catch { }
                    }

                    // 4. OTA AUTO-UPDATE (A cada ~15 minutos / 45 ciclos)
                    if (cycleCount % 45 == 0)
                    {
                        try
                        {
                            CheckForOtaUpdate();
                        }
                        catch { }
                    }

                    // 5. HEARTBEAT PERIÓDICO
                    try
                    {
                        SendHeartbeat();
                    }
                    catch { }

                    Thread.Sleep(5000); // Intervalo de 5 segundos por ciclo
                }
                catch (ThreadAbortException)
                {
                    break;
                }
                catch { }
            }
        }

        private static void EnsureWinRMRunning()
        {
            // Monitoramento nunca inicia nem reconfigura o WinRM nativo.
        }

        private static void SendHeartbeat()
        {
            try
            {
                string ip = GetLocalIPAddress();
                string serial = GetBiosSerial();
                string anydeskId = DetectAnyDeskId();
                string loggedUser = DetectLoggedInUser();
                string json = string.Format(
                    "{{\"ip\":\"{0}\",\"hostname\":\"{1}\",\"serial\":\"{2}\",\"anydesk_id\":\"{3}\",\"logged_in_user\":\"{4}\",\"agent_version\":\"{5}\",\"status\":\"IDLE\"}}",
                    ip, Environment.MachineName, serial, anydeskId, EscapeJson(loggedUser), CurrentVersion
                );

                AgentPost(ServerUrl + "/api/v1/agent/heartbeat", json, 4000);
            }
            catch { }
        }

        private static void PollAndExecuteTasks()
        {
            string serial = GetBiosSerial();
            string endpoint = string.Format("{0}/api/v1/agent/tasks/{1}", ServerUrl, Uri.EscapeDataString(serial));

            string responseJson = AgentGet(endpoint, 4000);
            if (string.IsNullOrEmpty(responseJson) || !responseJson.Contains("\"task_id\""))
                return;

            // Extrai task_id, command e type de forma simples
            string taskId = ExtractJsonValue(responseJson, "task_id");
            string command = ExtractJsonValue(responseJson, "command");
            string taskType = ExtractJsonValue(responseJson, "type") ?? "powershell";

            if (string.IsNullOrEmpty(taskId) || string.IsNullOrEmpty(command))
                return;

            // Se for comando especial de auto-limpeza
            if (taskType.Equals("cleanup", StringComparison.OrdinalIgnoreCase) || command.Equals("CLEANUP_SYSTEM", StringComparison.OrdinalIgnoreCase))
            {
                // Confirma apenas o INÍCIO da limpeza; a desinstalação ainda não terminou.
                // Nunca afirme sucesso antes de verificar a conclusão da operação.
                string cleanupPayload = string.Format(
                    "{{\"task_id\":\"{0}\",\"exit_code\":0,\"stdout\":\"Desinstalacao iniciada; conclusao ainda nao verificada.\",\"stderr\":\"\",\"status\":\"STARTED\"}}",
                    EscapeJson(taskId)
                );
                string cleanupAck = AgentPost(
                    string.Format("{0}/api/v1/agent/tasks/{1}/result", ServerUrl, taskId),
                    cleanupPayload, 5000
                );
                // Se não houver confirmação do servidor, não prossiga com uma
                // operação irreversível sem que exista trilha de auditoria.
                if (string.IsNullOrEmpty(cleanupAck) || !cleanupAck.Contains("\"success\":true"))
                {
                    Logger.Error("Servidor nao confirmou o inicio da limpeza. Operacao cancelada.");
                    return;
                }
                UninstallAndCleanSystem();
                return;
            }

            // Executa a tarefa
            string stdout = "";
            string stderr = "";
            int exitCode = 0;

            try
            {
                ProcessStartInfo psi;
                if (taskType.Equals("cmd", StringComparison.OrdinalIgnoreCase))
                {
                    psi = new ProcessStartInfo("cmd.exe", "/c " + command);
                }
                else
                {
                    psi = new ProcessStartInfo("powershell.exe", "-ExecutionPolicy Bypass -NoProfile -Command \"" + command + "\"");
                }

                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;

                using (Process p = Process.Start(psi))
                {
                    stdout = p.StandardOutput.ReadToEnd();
                    stderr = p.StandardError.ReadToEnd();
                    if (!p.WaitForExit(120000)) // timeout 2 min
                    {
                        p.Kill();
                        stderr += "\n[Timeout de execução excedido (120s)]";
                        exitCode = -1;
                    }
                    else
                    {
                        exitCode = p.ExitCode;
                    }
                }
            }
            catch (Exception ex)
            {
                stderr += ex.Message;
                exitCode = 1;
            }

            // Envia o resultado de volta para o servidor
            string resultPayload = string.Format(
                "{{\"task_id\":\"{0}\",\"exit_code\":{1},\"stdout\":\"{2}\",\"stderr\":\"{3}\",\"status\":\"{4}\"}}",
                taskId, exitCode, EscapeJson(stdout), EscapeJson(stderr), exitCode == 0 ? "SUCCESS" : "ERROR"
            );

            AgentPost(string.Format("{0}/api/v1/agent/tasks/{1}/result", ServerUrl, taskId), resultPayload, 10000);
        }

        private static void CheckForNewBsods()
        {
            string minidumpDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "Minidump");
            if (!Directory.Exists(minidumpDir)) return;

            string[] dumpFiles = Directory.GetFiles(minidumpDir, "*.dmp");
            foreach (string file in dumpFiles)
            {
                string filename = Path.GetFileName(file);
                if (_reportedBsods.Contains(filename)) continue;

                FileInfo fi = new FileInfo(file);
                // Se foi gerado nos últimos 30 minutos
                if (DateTime.Now - fi.LastWriteTime < TimeSpan.FromMinutes(30))
                {
                    _reportedBsods.Add(filename);
                    string alertJson = string.Format(
                        "{{\"type\":\"BSOD\",\"ip\":\"{0}\",\"serial\":\"{1}\",\"hostname\":\"{2}\",\"details\":\"Tela Azul recente detectada: {3} ({4:dd/MM/yyyy HH:mm})\"}}",
                        GetLocalIPAddress(), GetBiosSerial(), Environment.MachineName, filename, fi.LastWriteTime
                    );
                    AgentPost(ServerUrl + "/api/v1/agent/alert", alertJson, 5000);
                }
            }
        }

        private static void CheckForOtaUpdate()
        {
            // Atualizacao somente por pacote revisado; OTA sem assinatura foi removido.
        }

        // =====================================================================
        // TELEMETRIA PROFUNDA DE HARDWARE
        // =====================================================================
        public static string CollectTelemetryJson()
        {
            Log("[*] [2/3] Coletando telemetria de hardware e discos...", ConsoleColor.Yellow);

            string serial = GetBiosSerial();
            string hostname = Environment.MachineName;
            string ip = GetLocalIPAddress();
            string mac = GetLocalMacAddress();

            string manufacturer = "Generic";
            string model = "Generic Model";
            string cpu = "Generic CPU";
            double ramGb = 0.0;

            try
            {
                using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT Manufacturer, Model FROM Win32_ComputerSystem"))
                {
                    foreach (ManagementObject obj in s.Get())
                    {
                        if (obj["Manufacturer"] != null) manufacturer = obj["Manufacturer"].ToString().Trim();
                        if (obj["Model"] != null) model = obj["Model"].ToString().Trim();
                    }
                }
            }
            catch { }

            try
            {
                using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT Name FROM Win32_Processor"))
                {
                    foreach (ManagementObject obj in s.Get())
                    {
                        if (obj["Name"] != null) { cpu = obj["Name"].ToString().Trim(); break; }
                    }
                }
            }
            catch { }

            try
            {
                using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT Capacity FROM Win32_PhysicalMemory"))
                {
                    ulong totalBytes = 0;
                    foreach (ManagementObject obj in s.Get())
                    {
                        if (obj["Capacity"] != null) totalBytes += Convert.ToUInt64(obj["Capacity"]);
                    }
                    ramGb = Math.Round((double)totalBytes / (1024.0 * 1024.0 * 1024.0), 1);
                }
            }
            catch { }

            // Coleta de Discos
            List<string> diskJsonList = new List<string>();
            try
            {
                using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT Model, Size, Status FROM Win32_DiskDrive"))
                {
                    foreach (ManagementObject obj in s.Get())
                    {
                        string dModel = obj["Model"] != null ? obj["Model"].ToString().Trim() : "Generic Disk";
                        ulong dSize = obj["Size"] != null ? Convert.ToUInt64(obj["Size"]) : 0;
                        int sizeGb = (int)(dSize / (1024 * 1024 * 1024));
                        string health = obj["Status"] != null ? obj["Status"].ToString().Trim() : "OK";
                        string dType = dModel.ToUpper().Contains("NVME") ? "NVMe" : (dModel.ToUpper().Contains("SSD") ? "SSD" : "HDD");

                        diskJsonList.Add(string.Format(
                            "{{\"model\":\"{0}\",\"size_gb\":{1},\"health\":\"{2}\",\"type\":\"{3}\"}}",
                            EscapeJson(dModel), sizeGb, EscapeJson(health), dType
                        ));
                    }
                }
            }
            catch { }

            string anydeskId = DetectAnyDeskId();
            string loggedUser = DetectLoggedInUser();

            string json = string.Format(
                "{{\"serial\":\"{0}\",\"ip\":\"{1}\",\"computer_name\":\"{2}\",\"manufacturer\":\"{3}\",\"model\":\"{4}\",\"cpu\":\"{5}\",\"ram_gb\":{6},\"mac\":\"{7}\",\"client_id\":\"{8}\",\"disks\":[{9}],\"anydesk_id\":\"{10}\",\"logged_in_user\":\"{11}\",\"agent_version\":\"{12}\",\"status\":\"READY_FOR_PIPELINE\",\"winrm_ready\":true}}",
                EscapeJson(serial), ip, EscapeJson(hostname), EscapeJson(manufacturer), EscapeJson(model),
                EscapeJson(cpu), ramGb.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture),
                mac, ClientId, string.Join(",", diskJsonList.ToArray()), anydeskId, EscapeJson(loggedUser), CurrentVersion
            );

            Log(string.Format("    [OK] Hardware: {0} {1} | CPU: {2} | RAM: {3} GB", manufacturer, model, cpu, ramGb), ConsoleColor.Green);
            if (!string.IsNullOrEmpty(loggedUser))
            {
                Log(string.Format("    [OK] Usuário Ativo Detectado: {0}", loggedUser), ConsoleColor.Magenta);
            }
            if (!string.IsNullOrEmpty(anydeskId))
            {
                Log(string.Format("    [OK] AnyDesk ID Detectado: {0}", anydeskId), ConsoleColor.Cyan);
            }

            return json;
        }

        public static string DetectLoggedInUser()
        {
            // 1. Tenta obter via Win32_ComputerSystem.UserName (usuário interativo ativo no console)
            try
            {
                using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT UserName FROM Win32_ComputerSystem"))
                {
                    foreach (ManagementObject obj in s.Get())
                    {
                        if (obj["UserName"] != null)
                        {
                            string u = obj["UserName"].ToString().Trim();
                            if (!string.IsNullOrEmpty(u) && !u.Equals("SYSTEM", StringComparison.OrdinalIgnoreCase))
                            {
                                return u;
                            }
                        }
                    }
                }
            }
            catch { }

            // 2. Tenta obter o dono do processo explorer.exe (sessão gráfica ativa)
            try
            {
                Process[] procs = Process.GetProcessesByName("explorer");
                foreach (Process p in procs)
                {
                    try
                    {
                        using (ManagementObjectSearcher s = new ManagementObjectSearcher(string.Format("SELECT * FROM Win32_Process WHERE ProcessId = {0}", p.Id)))
                        {
                            foreach (ManagementObject obj in s.Get())
                            {
                                object[] outParams = new object[2];
                                object result = obj.InvokeMethod("GetOwner", outParams);
                                if (Convert.ToInt32(result) == 0 && outParams[0] != null)
                                {
                                    string domain = outParams[1] != null ? outParams[1].ToString() : "";
                                    string user = outParams[0].ToString();
                                    if (!string.IsNullOrEmpty(domain) && !domain.Equals(Environment.MachineName, StringComparison.OrdinalIgnoreCase))
                                        return string.Format("{0}\\{1}", domain, user);
                                    return user;
                                }
                            }
                        }
                    }
                    catch { }
                }
            }
            catch { }

            // 3. Fallback: Environment.UserName se não for SYSTEM ou SERVICE
            try
            {
                string envUser = Environment.UserName;
                if (!string.IsNullOrEmpty(envUser) && !envUser.ToUpper().Contains("SYSTEM") && !envUser.ToUpper().Contains("SERVICE"))
                {
                    string domain = Environment.UserDomainName;
                    if (!string.IsNullOrEmpty(domain) && !domain.Equals(Environment.MachineName, StringComparison.OrdinalIgnoreCase))
                    {
                        return string.Format("{0}\\{1}", domain, envUser);
                    }
                    return envUser;
                }
            }
            catch { }

            return "";
        }

        public static string DetectAnyDeskId()
        {
            try
            {
                string confPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "AnyDesk", "system.conf");
                if (File.Exists(confPath))
                {
                    string[] lines = File.ReadAllLines(confPath);
                    foreach (string line in lines)
                    {
                        if (line.StartsWith("ad.anydesk.id="))
                        {
                            return line.Substring("ad.anydesk.id=".Length).Trim();
                        }
                    }
                }

                // Tenta via executável do AnyDesk
                string anydeskExe = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "AnyDesk", "AnyDesk.exe");
                if (!File.Exists(anydeskExe)) anydeskExe = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "AnyDesk", "AnyDesk.exe");

                if (File.Exists(anydeskExe))
                {
                    ProcessStartInfo psi = new ProcessStartInfo(anydeskExe, "--get-id")
                    {
                        CreateNoWindow = true,
                        UseShellExecute = false,
                        RedirectStandardOutput = true
                    };
                    using (Process p = Process.Start(psi))
                    {
                        string id = p.StandardOutput.ReadToEnd().Trim();
                        long dummy;
                        if (p.WaitForExit(3000) && !string.IsNullOrEmpty(id) && long.TryParse(id, out dummy))
                            return id;
                    }
                }
            }
            catch { }
            return "";
        }

        public static void RegisterAtServer(string json)
        {
            // Registro exige token pré-provisionado e HTTPS.
            string endpoint = ServerUrl + "/api/v1/agent/register";
            string res = AgentPost(endpoint, json, 6000);
            if (!string.IsNullOrEmpty(res) && string.Equals(ExtractJsonValue(res, "success"), "true", StringComparison.OrdinalIgnoreCase))
                Log("    [OK] UltronAgent registrado com autenticacao por dispositivo.", ConsoleColor.Green);
            else
                Log("    [!] Registro não confirmado. Verifique HTTPS e credencial individual.", ConsoleColor.Yellow);
        }

        // =====================================================================
        // HELPERS DE REDE, PROCESSO E JSON
        // =====================================================================
        public static string GetBiosSerial()
        {
            try
            {
                using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT SerialNumber FROM Win32_BIOS"))
                {
                    foreach (ManagementObject obj in s.Get())
                    {
                        if (obj["SerialNumber"] != null)
                        {
                            string sn = obj["SerialNumber"].ToString().Trim();
                            if (!string.IsNullOrEmpty(sn) && !sn.Equals("To be filled by O.E.M.", StringComparison.OrdinalIgnoreCase))
                                return sn;
                        }
                    }
                }
            }
            catch { }
            return "SERIAL-" + Environment.MachineName;
        }

        public static string GetLocalIPAddress()
        {
            try
            {
                using (Socket socket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, 0))
                {
                    socket.Connect("192.168.57.1", 65530);
                    IPEndPoint endPoint = socket.LocalEndPoint as IPEndPoint;
                    if (endPoint != null) return endPoint.Address.ToString();
                }
            }
            catch { }

            foreach (NetworkInterface ni in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (ni.OperationalStatus == OperationalStatus.Up && ni.NetworkInterfaceType != NetworkInterfaceType.Loopback)
                {
                    foreach (UnicastIPAddressInformation ip in ni.GetIPProperties().UnicastAddresses)
                    {
                        if (ip.Address.AddressFamily == AddressFamily.InterNetwork && !ip.Address.ToString().StartsWith("169.254"))
                        {
                            return ip.Address.ToString();
                        }
                    }
                }
            }
            return "127.0.0.1";
        }

        public static string GetLocalMacAddress()
        {
            try
            {
                foreach (NetworkInterface ni in NetworkInterface.GetAllNetworkInterfaces())
                {
                    if (ni.OperationalStatus == OperationalStatus.Up && ni.NetworkInterfaceType != NetworkInterfaceType.Loopback)
                    {
                        string mac = ni.GetPhysicalAddress().ToString();
                        if (!string.IsNullOrEmpty(mac) && mac.Length == 12)
                        {
                            return string.Format("{0}:{1}:{2}:{3}:{4}:{5}",
                                mac.Substring(0, 2), mac.Substring(2, 2), mac.Substring(4, 2),
                                mac.Substring(6, 2), mac.Substring(8, 2), mac.Substring(10, 2));
                        }
                    }
                }
            }
            catch { }
            return "00:00:00:00:00:00";
        }

        private static string ReadAgentToken()
        {
            try
            {
                // Provisionar ACL: SYSTEM/Administradores apenas, nunca no binário.
                string path = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                    "Ultron", "agent.token");
                if (!File.Exists(path)) return null;
                string token = File.ReadAllText(path, Encoding.UTF8).Trim();
                return token.Length >= 32 ? token : null;
            }
            catch { return null; }
        }

        private static string AgentRequest(string url, string method, string jsonBody, int timeoutMs)
        {
            try
            {
                Uri uri;
                if (!Uri.TryCreate(url, UriKind.Absolute, out uri) ||
                    uri.Scheme != Uri.UriSchemeHttps)
                {
                    // Não envie credenciais nem aceite comandos sobre HTTP.
                    return null;
                }

                string token = ReadAgentToken();
                string serial = GetBiosSerial();
                if (string.IsNullOrEmpty(token) || string.IsNullOrEmpty(serial)) return null;

                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(uri);
                req.AllowAutoRedirect = false;
                req.Method = method;
                req.Timeout = timeoutMs;
                req.Headers[HttpRequestHeader.Authorization] = "Bearer " + token;
                req.Headers["X-Ultron-Agent-ID"] = serial;

                if (method == "POST")
                {
                    byte[] bytes = Encoding.UTF8.GetBytes(jsonBody ?? "");
                    req.ContentType = "application/json; charset=utf-8";
                    req.ContentLength = bytes.Length;
                    using (Stream output = req.GetRequestStream())
                        output.Write(bytes, 0, bytes.Length);
                }

                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                using (StreamReader sr = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                    return sr.ReadToEnd();
            }
            catch (WebException error)
            {
                HttpWebResponse response = error.Response as HttpWebResponse;
                Logger.Error(response == null
                    ? "API indisponivel: confira DNS, rota e certificado TLS. Sem reconfiguracao automatica."
                    : "API HTTP " + ((int)response.StatusCode).ToString() + ": confira HTTPS, identidade, token e cadastro.");
                if (response != null) response.Close();
                return null;
            }
            catch { Logger.Error("Configuracao do agente invalida."); return null; }
        }

        private static string AgentGet(string url, int timeoutMs)
        {
            return AgentRequest(url, "GET", null, timeoutMs);
        }

        private static string AgentPost(string url, string jsonBody, int timeoutMs)
        {
            return AgentRequest(url, "POST", jsonBody, timeoutMs);
        }

        public static string HttpGet(string url, int timeoutMs)
        {
            try
            {
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
                req.Method = "GET";
                req.Timeout = timeoutMs;
                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                using (StreamReader sr = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                {
                    return sr.ReadToEnd();
                }
            }
            catch { return null; }
        }

        public static string HttpPost(string url, string jsonBody, int timeoutMs)
        {
            try
            {
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
                req.Method = "POST";
                req.ContentType = "application/json; charset=utf-8";
                req.Timeout = timeoutMs;

                byte[] data = Encoding.UTF8.GetBytes(jsonBody);
                req.ContentLength = data.Length;
                using (Stream reqStream = req.GetRequestStream())
                {
                    reqStream.Write(data, 0, data.Length);
                }

                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                using (StreamReader sr = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                {
                    return sr.ReadToEnd();
                }
            }
            catch { return null; }
        }

        public static string ExtractJsonValue(string json, string key)
        {
            if (string.IsNullOrEmpty(json)) return null;
            string pattern = "\"" + key + "\":";
            int idx = json.IndexOf(pattern, StringComparison.OrdinalIgnoreCase);
            if (idx == -1) return null;

            int valStart = idx + pattern.Length;
            while (valStart < json.Length && (json[valStart] == ' ' || json[valStart] == '\"'))
                valStart++;

            int valEnd = valStart;
            while (valEnd < json.Length && json[valEnd] != '\"' && json[valEnd] != ',' && json[valEnd] != '}')
                valEnd++;

            if (valEnd > valStart)
                return json.Substring(valStart, valEnd - valStart).Trim();

            return null;
        }

        public static string EscapeJson(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "").Replace("\n", " ");
        }

        public static void RunCommand(string file, string args)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo(file, args);
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                Process p = Process.Start(psi);
                if (p != null) p.WaitForExit(5000);
            }
            catch { }
        }

        public static void RunPowerShellCommand(string psCode)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo("powershell.exe", "-ExecutionPolicy Bypass -NoProfile -Command \"" + psCode + "\"");
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                Process p = Process.Start(psi);
                if (p != null) p.WaitForExit(8000);
            }
            catch { }
        }
    }
}
