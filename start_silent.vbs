Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "G:\QtPrjt\superwuziqi\stm32"
WshShell.Run "pythonw.exe G:\QtPrjt\superwuziqi\stm32\miku_monitor.py --auto", 0, False
