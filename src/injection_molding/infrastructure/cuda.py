import sys
import os
import builtins
from types import ModuleType

# 1. 提前定义 dummy torch.cuda 模块
cuda = ModuleType('torch.cuda')
cuda.__path__ = []  # 标记为 package
cuda.is_available = lambda: False
cuda.device_count = lambda: 0
cuda.is_initialized = False
cuda._initialized = False
cuda._is_in_bad_fork = False

# 模拟核心类，防止 torch.multiprocessing.reductions 等内部调用报错
class DummyClass:
    def __init__(self, *args, **kwargs): pass
    def __getattr__(self, name): return lambda *args, **kwargs: None

cuda.Event = DummyClass
cuda.Stream = DummyClass
cuda._utils = ModuleType('torch.cuda._utils')
cuda._utils._get_device_index = lambda device, optional=False, allow_unknown_device=False: None

# 2. 模拟常用的子模块
for sub in ['amp', 'sparse', 'random', 'graphs', 'streams', 'nvtx', 'profiler', '_lazy', '_pynvml', 'nccl', 'comm', 'memory']:
    m = ModuleType(f'torch.cuda.{sub}')
    m.__path__ = []
    setattr(cuda, sub, m)
    sys.modules[f'torch.cuda.{sub}'] = m

# 为 amp 特别设置
cuda.amp.autocast = lambda *args, **kwargs: (lambda x: x)
cuda.amp.GradScaler = DummyClass

# 注册到 sys.modules
sys.modules['torch.cuda'] = cuda
sys.modules['torch.cuda._utils'] = cuda._utils

# 3. 关键修复：使用 import hook 解决循环导入时的 AttributeError
_orig_import = builtins.__import__

def _hooked_import(name, globals=None, locals=None, fromlist=(), level=0):
    module = _orig_import(name, globals, locals, fromlist, level)
    
    # 每当导入 torch 或其子模块时，确保 torch.cuda 属性存在
    if name == 'torch' or (isinstance(name, str) and name.startswith('torch.')):
        torch_mod = sys.modules.get('torch')
        if torch_mod and not hasattr(torch_mod, 'cuda'):
            torch_mod.cuda = sys.modules.get('torch.cuda')
            
    return module

# 替换全局 import
builtins.__import__ = _hooked_import

# 4. 环境变量设置
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ["TORCH_SKIP_CUDA_INIT"] = "1"
