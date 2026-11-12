"""Configure once; normal launches need neither pip nor an internet connection."""
import argparse,hashlib,json,os,socket,subprocess,sys,time,urllib.request,webbrowser
import re
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def dependency_fingerprint(root=ROOT):
    return hashlib.sha256((Path(root)/'requirements.lock').read_bytes()).hexdigest()


def env_python(root=ROOT):
    return Path(root)/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')


def dependencies_ok(python,root=ROOT):
    wanted={line.split(';')[0].split('==')[0]:line.split(';')[0].split('==')[1].strip() for line in (Path(root)/'requirements.lock').read_text().splitlines() if '==' in line and not line.startswith('#') and (';' not in line or os.name=='nt')}
    code='import importlib.metadata as m; wanted='+repr(wanted)+'; assert all(m.version(k)==v for k,v in wanted.items())'
    return subprocess.run([str(python),'-c',code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0


def install_dependencies(python, root, log):
    """Keep the install log and surface real package progress in the launcher."""
    started = time.monotonic()
    finished = threading.Event()

    def heartbeat():
        while not finished.wait(15):
            print(f'    仍在处理依赖 · 已等待 {int(time.monotonic() - started)} 秒', flush=True)

    command = [str(python), '-u', '-m', 'pip', 'install', '--progress-bar', 'raw',
               '--disable-pip-version-check', '-r', str(root/'requirements.lock')]
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    with subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf-8', errors='replace', env=env) as process:
        timer = threading.Thread(target=heartbeat, daemon=True)
        timer.start()
        last_progress = 0.0
        try:
            for line in process.stdout:
                log.write(line)
                log.flush()
                message = line.strip()
                progress = re.fullmatch(r'Progress (\d+) of (\d+|None)', message)
                if progress:
                    downloaded, total = progress.groups()
                    now = time.monotonic()
                    if now - last_progress >= 2 or downloaded == total:
                        amount = f'{int(downloaded) / 1_000_000:.1f} MB'
                        if total != 'None':
                            amount += f' / {int(total) / 1_000_000:.1f} MB'
                        print(f'    当前文件已下载 {amount}', flush=True)
                        last_progress = now
                elif message.startswith(('Collecting ', 'Downloading ', 'Using cached ', 'ERROR:', 'WARNING: Retrying')):
                    print('    '+message, flush=True)
                elif message.startswith('Installing collected packages'):
                    print('    下载完成，正在安装依赖…', flush=True)
            return process.wait()
        finally:
            finished.set()
            timer.join()
            if process.poll() is None:
                process.terminate()


def ensure_environment(root=ROOT,repair=False):
    print('[1/3] 检查Python与本机独立环境…',flush=True)
    if sys.version_info[:2]!=(3,12) or sys.maxsize<=2**32:raise RuntimeError('本批锁定依赖需要64位Python 3.12。请安装对应版本后启动：https://www.python.org/downloads/windows/')
    root=Path(root);local=root/'local';local.mkdir(exist_ok=True);python=env_python(root)
    if python.exists():
        version=subprocess.run([str(python),'-c','import sys; print(str(sys.version_info.major)+"."+str(sys.version_info.minor))'],capture_output=True,text=True)
        if version.returncode or version.stdout.strip()!='3.12':(root/'.venv').rename(root/('.venv-old-'+str(time.time_ns())))
    if not python.exists():
        print('[1/3] 首次配置：正在创建独立环境…',flush=True)
        subprocess.run([sys.executable,'-m','venv',str(root/'.venv')],check=True)
    stamp=local/'environment.json';fingerprint=dependency_fingerprint(root)
    try:current=json.loads(stamp.read_text())
    except (ValueError,OSError):current={}
    if repair or current.get('requirements')!=fingerprint or not dependencies_ok(python,root):
        print('[2/3] 正在下载和安装锁定依赖。首次需要联网，请保持此窗口打开。',flush=True)
        with open(local/'install.log','a',encoding='utf-8') as log:
            if install_dependencies(python, root, log):
                raise RuntimeError('依赖安装失败。请根据上方错误检查网络，再运行 repair_windows.bat 重试。完整日志：local/install.log')
            print('[3/3] 正在校验已安装依赖…',flush=True)
            check=subprocess.run([str(python),'-m','pip','check'],stdout=log,stderr=log)
            if check.returncode or not dependencies_ok(python,root):raise RuntimeError('依赖校验失败，请运行 repair_windows.bat')
        stamp.write_text(json.dumps({'requirements':fingerprint}),encoding='utf-8')
    else:print('[2/3] 复用已安装依赖，跳过联网安装。',flush=True)
    print('[3/3] 环境校验通过。日常启动无需重复安装依赖。',flush=True)
    return python


def available_port(preferred=8501):
    with socket.socket() as sock:
        try:sock.bind(('127.0.0.1',preferred))
        except OSError:sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def restore_dialog(python):
    try:
        import tkinter as tk
        from tkinter import filedialog,messagebox
        app=tk.Tk();app.withdraw()
    except Exception:
        path=input('请输入备份ZIP或DB完整路径：').strip().strip('"')
        confirmed=input('关闭应用和采集后，输入 RESTORE 确认替换当前数据：').strip()=='RESTORE'
        if path and confirmed:subprocess.run([str(python),'-m','creatorlab.recovery',path],cwd=ROOT,check=True)
        return
    path=filedialog.askopenfilename(title='选择CLab备份',filetypes=[('CLab backup','*.zip *.db')])
    if path and messagebox.askyesno('恢复数据','请先关闭CLab及采集窗口。恢复将替换当前数据，并先保留当前文件的保护副本。继续？'):
        subprocess.run([str(python),'-m','creatorlab.recovery',path],cwd=ROOT,check=True)
        messagebox.showinfo('恢复完成','数据已恢复，可以重新启动CLab。')
    app.destroy()


def launch_app(python):
    print('正在启动工作台页面，首次打开可能需要稍等…',flush=True)
    from creatorlab.maintenance import database_gate
    local=ROOT/'local';runtime=local/'runtime.json'
    try:
        with database_gate(local/'ui-instance',timeout=.2):
            url='http://127.0.0.1:'+str(available_port())
            runtime.write_text(json.dumps({'url':url}),encoding='utf-8')
            with open(local/'app.log','a',encoding='utf-8') as log:
                process=subprocess.Popen([str(python),'-m','streamlit','run',str(ROOT/'app.py'),'--server.address','127.0.0.1','--server.port',url.rsplit(':',1)[1],'--server.headless','true'],cwd=ROOT,stdout=log,stderr=log)
                try:
                    ready=False;deadline=time.monotonic()+45
                    while time.monotonic()<deadline:
                        if process.poll() is not None:raise RuntimeError('应用未能启动，请查看 local/app.log 或运行 repair_windows.bat')
                        try:
                            with urllib.request.urlopen(url+'/_stcore/health',timeout=.5) as response:ready=response.status==200
                            if ready:
                                try:webbrowser.open(url)
                                except (OSError,webbrowser.Error):pass
                                break
                        except OSError:pass
                        time.sleep(.25)
                    if not ready:raise RuntimeError('启动未就绪，请运行修复脚本或查看 local/app.log')
                    print('CLab 已启动：'+url+'；保持此窗口打开，Ctrl+C退出。',flush=True)
                    process.wait()
                finally:
                    for stop in ('sync_stop','bilibili_sync_stop'):(local/stop).touch()
                    if process.poll() is None:
                        process.terminate()
                        try:process.wait(timeout=10)
                        except subprocess.TimeoutExpired:process.kill();process.wait()
    except RuntimeError as exc:
        if '另一个窗口' not in str(exc):raise
        try:
            import re
            url=json.loads(runtime.read_text())['url']
            if re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}',url):webbrowser.open(url);return
        except (OSError,ValueError,KeyError):pass
        raise RuntimeError('另一个CLab窗口正在运行，请关闭后重试')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--setup-only',action='store_true');parser.add_argument('--repair',action='store_true');parser.add_argument('--restore',action='store_true');args=parser.parse_args()
    try:
        if args.repair:
            from creatorlab.maintenance import database_gate
            from creatorlab.bilibili_import import job_running
            if job_running(ROOT) or job_running(ROOT,'douyin'):raise RuntimeError('请先关闭全部采集窗口，再修复环境')
            with database_gate(ROOT/'local'/'ui-instance',timeout=.2):
                python=ensure_environment(repair=True)
        else:python=ensure_environment()
        if args.restore:restore_dialog(python)
        elif not args.setup_only:launch_app(python)
        else:print('环境已就绪。双击 start_windows.bat 打开工作台；首次可先看示例，再添加自己的账号。')
    except KeyboardInterrupt:return 0
    except (RuntimeError,OSError,subprocess.SubprocessError) as exc:print(str(exc),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
