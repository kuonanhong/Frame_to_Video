"""Conservative CPU memory preflight; estimates, never a hardware benchmark."""
import os
from pathlib import Path
import platform
import subprocess

GIB = 1024**3
MIN_GIB = {'qwen-text':2,'liveportrait':4,'controlnet-canny':12,'multidiffusion':12,
    'flux-klein':48,'ltx-video':32,'cogvideox':48}

def available_memory():
    system = platform.system()
    if system == 'Linux':
        try:
            info = dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
            available = int(info['MemAvailable'].split()[0])*1024
            # Respect a container's hard limit, accounting for reclaimable file cache.
            limit_path = Path('/sys/fs/cgroup/memory.max')
            if limit_path.exists() and limit_path.read_text().strip() != 'max':
                limit = int(limit_path.read_text())
                current = int(Path('/sys/fs/cgroup/memory.current').read_text())
                stats = dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())
                available = min(available,limit,max(0,limit-current+int(stats.get('inactive_file',0))))
            return available
        except (OSError,ValueError,KeyError):
            return None
    if system == 'Darwin':
        try:
            # vm_stat includes free/inactive/purgeable pages; this is an estimate.
            output = subprocess.check_output(['vm_stat'],text=True,timeout=5)
            page_size = int(output.split('page size of ')[1].split(' bytes')[0])
            values = dict(line.split(':',1) for line in output.splitlines()[1:] if ':' in line)
            return sum(int(values.get(key,'0').strip().rstrip('.'))
                for key in ('Pages free','Pages inactive','Pages purgeable'))*page_size
        except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):
            return None
    if system == 'Windows':
        try:
            import ctypes
            class Memory(ctypes.Structure):
                _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong)
                    for name in ('totalPhys','availPhys','totalPage','availPage','totalVirtual','availVirtual','availExtended')]
            memory = Memory()
            memory.length = ctypes.sizeof(Memory)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
                return memory.availPhys
        except (AttributeError,OSError):
            pass
    return None

def memory_check(expert):
    available = available_memory()
    minimum = MIN_GIB[expert]
    low = available is not None and available < minimum*GIB
    override = os.environ.get('FRAME_EXPERT_ALLOW_LOW_MEMORY') == '1'
    return dict(required_gib_estimate=minimum,available_gib_estimate=round(available/GIB,1) if available is not None else None,
        ready=not low or override,override=override,warning=(
            f'Estimated available memory is below this expert’s conservative {minimum} GiB CPU preflight. This is an estimate, not a benchmark.' if low else None))
