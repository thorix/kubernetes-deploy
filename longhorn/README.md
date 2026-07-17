# Longhorn Storage on Talos Linux

Longhorn is a distributed block storage system for Kubernetes that provides persistent storage for your workloads.

## Prerequisites for Talos Linux

Before deploying Longhorn, you must configure your Talos cluster with the following requirements.

### 1. System Extensions

Verify that you have the required system extension installed:

```bash
# Check if util-linux-tools is installed
talosctl get extensions
```

You should see something like this:
```
❯ talosctl get extensions -n ${CONTROL_PLANE_1_IP}
NODE        NAMESPACE   TYPE              ID   VERSION   NAME               VERSION
192.0.2.50   runtime     ExtensionStatus   0    1         util-linux-tools   2.41.2
192.0.2.50   runtime     ExtensionStatus   1    1         tailscale          1.92.3
192.0.2.50   runtime     ExtensionStatus   2    1         iscsi-tools        v0.2.0
192.0.2.50   runtime     ExtensionStatus   3    1         schematic          cd59cbf6602c7c3c55b09439108e0b9b97707b2e39b5c358b8425a227031eb87
```

### 2. Kubelet Configuration

You **MUST** configure kubelet to mount `/var/mnt/longhorn` on all nodes. This path persists across Talos upgrades.

Add the following to your Talos machine configuration:

```yaml
machine:
  kubelet:
    extraMounts:
      - destination: /var/mnt/longhorn
        type: bind
        source: /var/mnt/longhorn
        options:
          - bind
          - rshared
          - rw
```

### 3. Apply Configuration to Talos Cluster

**For all nodes:**

```bash
# Edit your Talos machine config to add the kubelet extraMounts
# Then apply the configuration

# For control plane nodes:
talosctl apply-config --nodes <control-plane-ip> --file controlplane.yaml

# For worker nodes:
talosctl apply-config --nodes <worker-ip> --file worker.yaml

# Reboot nodes to apply changes (if required):
talosctl reboot --nodes <node-ip>
```

**Verify the mount is present:**

```bash
talosctl -n <node-ip> ls /var/mnt/longhorn
```

You should see the directory exists (even if empty initially).

## Deployment

Once the Talos configuration is complete, ArgoCD will automatically deploy Longhorn when you commit this configuration.

### Configuration Summary

- **Namespace**: `longhorn-system` (created by Longhorn)
- **Storage Path**: `/var/mnt/longhorn` (persists across Talos upgrades)
- **Default Replicas**: 2
- **Nodes**: All nodes used for storage
- **UI Access**: https://longhorn.rye

## Post-Deployment

### Access the Longhorn UI

Once deployed, access the Longhorn UI at:
- URL: http://longhorn.rye
- View volumes, nodes, settings, and storage statistics

### Create Your First Volume

Longhorn automatically creates a StorageClass named `longhorn`.

Test it with a PVC:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: longhorn
  resources:
    requests:
      storage: 1Gi
```

### Verify Installation

```bash
# Check Longhorn pods are running
kubectl get pods -n longhorn-system

# Check nodes are ready
kubectl get nodes -n longhorn-system

# List storage classes
kubectl get storageclass
```

You should see the `longhorn` StorageClass available.

## Talos-Specific Notes

### Why /var/mnt/longhorn?

On Talos Linux, most of the root filesystem is ephemeral and gets reset on upgrades. Only specific paths persist:

- `/var/mnt/*` - Persists across upgrades ✅
- `/var/lib/*` - **Does NOT persist** ❌

Using `/var/mnt/longhorn` ensures your storage data survives Talos upgrades.

### System Extensions Installed

- `util-linux-tools` - Provides disk utilities (mkfs, mount, etc.)
- `iscsi-tools` - needed (no iSCSI hardware)

### Storage Behavior

- Longhorn will use available disk space on each node
- Default replica count: 2 (each volume stored on 2 nodes)
- Storage overprovisioning: 200% (can allocate 2x physical storage)
- Minimal available: 25% (stops allocating when <25% free)

## Troubleshooting

### Pods stuck in Pending

Check if nodes have the mount:
```bash
talosctl -n <node-ip> ls /var/mnt/longhorn
```

If missing, apply the kubelet configuration and reboot.

### No storage capacity

Check node capacity in Longhorn UI or:
```bash
kubectl get nodes.longhorn.io -n longhorn-system
```

Verify nodes have available disk space.

### Volumes stuck in Attaching

Check pod logs:
```bash
kubectl logs -n longhorn-system -l app=longhorn-manager
```

## Useful Commands

```bash
# View all Longhorn resources
kubectl get all -n longhorn-system

# Check Longhorn settings
kubectl get settings -n longhorn-system

# View volumes
kubectl get volumes -n longhorn-system

# View nodes
kubectl get nodes.longhorn.io -n longhorn-system

# Check storage class
kubectl describe storageclass longhorn
```

## Upgrading Longhorn

To upgrade to a newer version:

1. Update the version in `Chart.yaml`
2. Run `helm dependency update`
3. Commit and push
4. ArgoCD will handle the upgrade

## References

- [Longhorn Talos Linux Support](https://longhorn.io/docs/1.10.1/advanced-resources/os-distro-specific/talos-linux-support/)
- [Talos Linux Storage Guide](https://www.talos.dev/latest/kubernetes-guides/configuration/storage/)
- [Longhorn Documentation](https://longhorn.io/docs/)
