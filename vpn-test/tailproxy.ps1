param(
  [string]$ListenAddress = "100.79.230.2",
  [int]$Port = 18080
)

$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

namespace TailProxy {
  public static class Program {
    public static void Run(string listenAddress, int listenPort) {
      var listener = new TcpListener(IPAddress.Parse(listenAddress), listenPort);
      listener.Start(256);
      Console.WriteLine("TailProxy listening on " + listenAddress + ":" + listenPort);
      while (true) {
        var client = listener.AcceptTcpClient();
        ThreadPool.QueueUserWorkItem(_ => Handle(client));
      }
    }

    private static void Handle(TcpClient client) {
      using (client) {
        client.NoDelay = true;
        var clientStream = client.GetStream();
        string header = ReadHeader(clientStream);
        if (String.IsNullOrWhiteSpace(header)) return;

        string firstLine = header.Split(new string[] { "\r\n" }, StringSplitOptions.None)[0];
        string[] parts = firstLine.Split(' ');
        if (parts.Length < 3 || !parts[0].Equals("CONNECT", StringComparison.OrdinalIgnoreCase)) {
          WriteAscii(clientStream, "HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n");
          return;
        }

        string host;
        int port;
        if (!TryParseTarget(parts[1], out host, out port)) {
          WriteAscii(clientStream, "HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n");
          return;
        }

        TcpClient server = new TcpClient();
        server.NoDelay = true;
        try {
          server.Connect(host, port);
        } catch {
          server.Close();
          WriteAscii(clientStream, "HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n");
          return;
        }

        using (server) {
          WriteAscii(clientStream, "HTTP/1.1 200 Connection Established\r\nProxy-Agent: TailProxy\r\n\r\n");
          var serverStream = server.GetStream();
          var t = new Thread(() => Pump(clientStream, serverStream));
          t.IsBackground = true;
          t.Start();
          Pump(serverStream, clientStream);
        }
      }
    }

    private static bool TryParseTarget(string target, out string host, out int port) {
      host = "";
      port = 443;
      if (String.IsNullOrWhiteSpace(target)) return false;

      if (target.StartsWith("[")) {
        int end = target.IndexOf(']');
        if (end < 0) return false;
        host = target.Substring(1, end - 1);
        int colon = target.IndexOf(':', end);
        if (colon >= 0 && !Int32.TryParse(target.Substring(colon + 1), out port)) return false;
        return host.Length > 0;
      }

      int idx = target.LastIndexOf(':');
      if (idx < 1) return false;
      host = target.Substring(0, idx);
      return Int32.TryParse(target.Substring(idx + 1), out port);
    }

    private static string ReadHeader(Stream stream) {
      byte[] one = new byte[1];
      MemoryStream ms = new MemoryStream();
      int matched = 0;
      byte[] marker = new byte[] { 13, 10, 13, 10 };

      while (ms.Length < 65536) {
        int n = stream.Read(one, 0, 1);
        if (n <= 0) break;
        ms.WriteByte(one[0]);
        if (one[0] == marker[matched]) {
          matched++;
          if (matched == marker.Length) break;
        } else {
          matched = (one[0] == marker[0]) ? 1 : 0;
        }
      }

      return Encoding.ASCII.GetString(ms.ToArray());
    }

    private static void WriteAscii(Stream stream, string text) {
      byte[] bytes = Encoding.ASCII.GetBytes(text);
      stream.Write(bytes, 0, bytes.Length);
      stream.Flush();
    }

    private static void Pump(Stream input, Stream output) {
      byte[] buffer = new byte[65536];
      try {
        while (true) {
          int n = input.Read(buffer, 0, buffer.Length);
          if (n <= 0) break;
          output.Write(buffer, 0, n);
          output.Flush();
        }
      } catch {
      }
    }
  }
}
'@

[TailProxy.Program]::Run($ListenAddress, $Port)
