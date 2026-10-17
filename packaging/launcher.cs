// WE 壁纸播放器 — 免安装版启动器
// 优先使用随包的 runtime\pythonw.exe，找不到再回退到系统 Python。
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Launcher
{
    [STAThread]
    private static int Main()
    {
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        string script = Path.Combine(baseDir, "we_player.py");

        if (!File.Exists(script))
        {
            MessageBox.Show(
                "找不到 we_player.py。\n\n请把整个文件夹一起解压后再运行，不要只复制启动器。",
                "WE 壁纸播放器", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }

        string exe = Path.Combine(baseDir, Path.Combine("runtime", "pythonw.exe"));
        if (!File.Exists(exe)) exe = FindSystemPythonw();

        if (exe == null)
        {
            MessageBox.Show(
                "没找到可用的 Python 运行环境。\n\n" +
                "免安装版应自带 runtime\\pythonw.exe —— 请确认解压完整；\n" +
                "或者装一个 Python 3.8+（安装时勾选 Add Python to PATH）再试。",
                "WE 壁纸播放器", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }

        try
        {
            ProcessStartInfo psi = new ProcessStartInfo(exe, "\"" + script + "\"");
            psi.WorkingDirectory = baseDir;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            Process.Start(psi);
            return 0;
        }
        catch (Exception ex)
        {
            MessageBox.Show("启动失败：" + ex.Message, "WE 壁纸播放器",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private static string FindSystemPythonw()
    {
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string[] candidates = new string[]
        {
            Path.Combine(local, @"Programs\Python\Python313\pythonw.exe"),
            Path.Combine(local, @"Programs\Python\Python312\pythonw.exe"),
            Path.Combine(local, @"Programs\Python\Python311\pythonw.exe"),
            Path.Combine(local, @"Programs\Python\Python310\pythonw.exe"),
            @"C:\Python313\pythonw.exe",
            @"C:\Python312\pythonw.exe",
        };
        foreach (string c in candidates)
        {
            if (File.Exists(c)) return c;
        }
        return null;
    }
}
