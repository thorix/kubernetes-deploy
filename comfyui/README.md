# ComfyUI Deployment

ComfyUI is a powerful and modular Stable Diffusion GUI with a graph/nodes interface for creating complex AI image generation workflows.

## Overview

This deployment:
- Uses the `yanwk/comfyui-boot` Docker image with AMD ROCm support
- Supports optional AMD GPU acceleration via ROCm
- Provides persistent storage for models and outputs
- Includes HTTPRoute for external access
- Can run in CPU-only mode (slower but functional)

## Prerequisites

### Required
- Kubernetes cluster with Gateway API support
- Persistent storage (recommended: Longhorn)
- At least 4GB RAM available

### Optional (for GPU acceleration)
- AMD GPU nodes with 8GB+ VRAM (e.g., Radeon RX 7000 series, Ryzen AI, Instinct series)
- AMD GPU Device Plugin installed
- ROCm drivers installed on nodes
- Compatible AMD GPUs: RDNA 2/3, Ryzen AI, or Instinct series

## GPU Setup (Optional but Recommended)

ComfyUI performs significantly better with GPU acceleration. Without a GPU, image generation can take minutes instead of seconds.

### 1. Install AMD GPU Device Plugin

```bash
kubectl create -f https://raw.githubusercontent.com/ROCm/k8s-device-plugin/master/k8s-ds-amdgpu-dp.yaml
```

This DaemonSet will run on all AMD GPU nodes and expose `amd.com/gpu` resources.

### 2. Verify GPU Availability

Check that AMD GPUs are visible to Kubernetes:
```bash
kubectl get nodes -o json | jq '.items[].status.capacity."amd.com/gpu"'
```

You can also check node labels created by the device plugin:
```bash
kubectl get nodes -o json | jq '.items[].metadata.labels | with_entries(select(.key | startswith("amd.com")))'
```

### 3. Enable GPU in Values

Update `values.prod.yaml`:
```yaml
image:
  tag: "rocm"  # ROCm for AMD GPUs

gpu:
  enabled: true
  type: "amd"
  count: 1
  tolerations:
  - key: amd.com/gpu
    operator: Exists
    effect: NoSchedule
```

### 4. ROCm Notes

- Ensure ROCm drivers are installed on the host nodes
- For Talos Linux with AMD GPUs, you may need to use system extensions for ROCm drivers
- Check [AMD ROCm ComfyUI documentation](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/advanced/advancedrad/windows/comfyui/installcomfyui.html) for compatibility
- The `rocm` image tag includes ROCm 6.x libraries

## Installation

This deployment is automatically discovered by ArgoCD via the ApplicationSet.

### Manual Installation (for testing)

```bash
# Install with default values (CPU-only mode)
helm install comfyui . -n comfyui --create-namespace

# Install with GPU support (requires GPU setup)
helm install comfyui . -n comfyui --create-namespace -f values.prod.yaml
```

## Storage

ComfyUI requires persistent storage for:
- **Models**: Stable Diffusion models, VAEs, LoRAs, etc. (can be 10s of GB)
- **Outputs**: Generated images and workflows

The deployment creates two PVCs:
- `comfyui-models`: Stores AI models at `/root/ComfyUI/models`
- `comfyui-outputs`: Stores generated images at `/root/ComfyUI/output`

Default storage size: 50Gi (configurable in values.yaml)

### Model Management

Models must be manually downloaded to the persistent volume. There are several approaches:

#### Option 1: Use ComfyUI Manager (Recommended)

1. Access ComfyUI UI at your configured hostname (e.g., `comfy.rye`)
2. Install ComfyUI Manager from the settings
3. Use the Manager to download models directly from the UI

#### Option 2: Manual Upload via kubectl

```bash
# Copy a model file to the models PVC
kubectl cp path/to/model.safetensors \
  comfyui/comfyui-0:/root/ComfyUI/models/checkpoints/model.safetensors

# List models in the pod
kubectl exec -n comfyui comfyui-0 -- ls -lh /root/ComfyUI/models/checkpoints/
```

#### Option 3: InitContainer with Model Downloads

Add an initContainer to the deployment that downloads models on startup. This is useful for automated deployments with specific model requirements.

### Popular Models to Get Started

- **Stable Diffusion XL**: Large, high-quality model (~6GB)
- **Stable Diffusion 1.5**: Smaller, faster model (~4GB)
- **VAE**: Variational autoencoder for better colors (~300MB)

Models can be downloaded from:
- [Hugging Face](https://huggingface.co/models?pipeline_tag=text-to-image)
- [Civitai](https://civitai.com/)

## Configuration

### Key Values

| Parameter | Description | Default |
|-----------|-------------|---------|
| `hostname` | Domain for HTTPRoute access | `""` (disabled) |
| `gpu.enabled` | Enable AMD GPU support | `false` |
| `gpu.type` | GPU type (set to "amd") | `amd` |
| `gpu.count` | Number of GPUs to request | `1` |
| `persistence.enabled` | Enable persistent storage | `true` |
| `persistence.size` | Storage size per PVC | `50Gi` |
| `image.tag` | Docker image tag (rocm, cpu) | `cpu` |

### Environment-Specific Values

- **values.yaml**: Base configuration with CPU mode
- **values.prod.yaml**: Production settings (AMD ROCm, 100Gi storage, higher resources)
- **values.dev.yaml**: Development settings (20Gi storage, lower resources)

### Available Image Tags

- `rocm`: ROCm for AMD GPUs (use after GPU device plugin is installed)
- `cpu`: CPU-only mode (slower, no GPU required)

## Accessing ComfyUI

### Via HTTPRoute (External Access)

Set `hostname` in your values file:
```yaml
hostname: comfy.rye
```

Then access at: `http://comfy.rye`

### Via Port Forward (Local Access)

```bash
kubectl port-forward -n comfyui svc/comfyui 8188:80
```

Then access at: `http://localhost:8188`

## CPU-Only Mode

The deployment starts in CPU mode by default. CPU mode is functional but very slow. Expect 5-10 minutes per image vs 10-30 seconds with GPU.

To force CPU mode with ROCm image:
```yaml
env:
  - name: COMMANDLINE_ARGS
    value: "--cpu"
```

## Troubleshooting

### Pod Stuck in Pending State

Check GPU resources:
```bash
kubectl describe pod -n comfyui -l app.kubernetes.io/name=comfyui
```

Common issues:
- No GPU nodes available: Disable GPU in values or add GPU nodes
- GPU already allocated: Increase GPU node count or reduce GPU requests
- Missing AMD device plugin: Install the k8s-device-plugin

### Out of Memory Errors

Increase memory limits in values.yaml:
```yaml
resources:
  limits:
    memory: 16Gi  # Or higher
```

### Models Not Found

Check PVC is mounted and contains models:
```bash
kubectl exec -n comfyui comfyui-0 -- ls -la /root/ComfyUI/models/
```

If empty, see "Model Management" section above.

### Slow Performance

1. **Enable GPU**: See "GPU Setup" section
2. **Check GPU usage**:
   ```bash
   kubectl exec -n comfyui comfyui-0 -- rocm-smi
   ```
3. **Use smaller models**: SD 1.5 is faster than SDXL
4. **Verify ROCm is being used**: Check logs for GPU detection messages

### RuntimeError: No HIP GPUs are available

This error occurs when using the `rocm` image without AMD GPU device plugin installed.

**Solutions:**
1. Install AMD GPU Device Plugin (see "GPU Setup" section)
2. **OR** switch to CPU mode by setting `image.tag: "cpu"` in values

### Image Generation Fails

Check logs:
```bash
kubectl logs -n comfyui -l app.kubernetes.io/name=comfyui
```

Common issues:
- Missing models: Download required models
- Insufficient VRAM: Reduce image resolution or use smaller models
- Incompatible workflow: Use workflows compatible with your ComfyUI version
- ROCm compatibility: Ensure your AMD GPU is compatible with ROCm

## Post-Deployment Setup

After deployment:

1. **Access the UI** at your configured hostname or via port-forward
2. **Install ComfyUI Manager** (optional but recommended)
3. **Download models** via Manager or manually
4. **Test with a simple workflow**: Load an example and generate an image

## Resource Requirements

### Minimum (CPU-only)
- CPU: 2 cores
- Memory: 4GB
- Storage: 20GB
- Expected performance: 5-10 minutes per image

### Recommended (with AMD GPU)
- CPU: 4 cores
- Memory: 8GB
- Storage: 50GB+
- GPU: 8GB+ VRAM
- Expected performance: 10-30 seconds per image

### Production (high quality, SDXL)
- CPU: 8 cores
- Memory: 16GB
- Storage: 100GB+
- GPU: 16GB+ VRAM (e.g., AMD Radeon RX 7900 XT/XTX)
- Expected performance: 15-45 seconds per image

## Additional Resources

**ComfyUI:**
- [ComfyUI GitHub](https://github.com/comfyanonymous/ComfyUI)
- [ComfyUI Documentation](https://docs.comfy.org/)
- [YanWenKun Docker Image](https://github.com/YanWenKun/ComfyUI-Docker)
- [ComfyUI Examples](https://comfyanonymous.github.io/ComfyUI_examples/)

**AMD GPU Support:**
- [AMD GPU Device Plugin](https://github.com/ROCm/k8s-device-plugin)
- [AMD GPU Device Plugin Documentation](https://instinct.docs.amd.com/projects/k8s-device-plugin/en/latest/)
- [AMD ROCm ComfyUI Documentation](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/advanced/advancedrad/windows/comfyui/installcomfyui.html)
- [ROCm Compatibility Matrix](https://rocm.docs.amd.com/)

## Notes

- **Container runs as root**: The ComfyUI Docker image requires root access to `/root` directory. This is standard for this image but should be considered in security policies.
- **First startup**: May take several minutes as ComfyUI initializes and loads extensions
- **Model downloads**: Can be large (10s of GB) - plan storage accordingly
- **GPU time-slicing**: Not configured by default but can be added for multi-tenant scenarios
- **ROCm compatibility**: Verify your AMD GPU is supported by ROCm before enabling GPU mode
- **Production workloads**: For multiple users, consider deploying multiple replicas with load balancing
