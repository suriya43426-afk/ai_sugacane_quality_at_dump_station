import torch
import sys
import platform

print("="*40)
print("   GPU Diagnostic Tool for AI-Sugarcane")
print("="*40)

print(f"Python Version: {sys.version.split()[0]}")
print(f"OS: {platform.system()} {platform.release()}")

try:
    print(f"Torhc Version: {torch.__version__}")
    cuda_avail = torch.cuda.is_available()
    print(f"CUDA Available: {cuda_avail}")
    
    if cuda_avail:
        print(f"Device Count: {torch.cuda.device_count()}")
        for i in range(torch.cuda.device_count()):
            print(f" - Device {i}: {torch.cuda.get_device_name(i)}")
        print(f"Current Device: {torch.cuda.current_device()}")
    else:
        print("\nReason for No GPU:")
        if not torch.backends.cudnn.enabled:
            print(" - cuDNN is disabled.")
        if "cpu" in torch.__version__:
            print(" - PyTorch installed is CPU-only version (no +cuXXX tag).")
        else:
            print(" - Drivers might be missing or CUDA version mismatch.")
            
except ImportError:
    print("ERROR: torch module not found. Is it installed?")

print("="*40)

if not torch.cuda.is_available():
    print("\nSUGGESTED FIX:")
    print("1. Uninstall current torch:  pip uninstall torch torchvision torchaudio -y")
    print("2. Install GPU version:")
    print("   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118")
    print("\n(Note: 'cu118' depends on your NVIDIA Driver version. check 'nvidia-smi')")
print("="*40)
