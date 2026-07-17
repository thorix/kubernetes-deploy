# Vault Backup and Restore Guide

This guide covers backing up and restoring HashiCorp Vault running on Kubernetes with file storage backend.

## Prerequisites

- Access to the Vault root token
- Original unseal keys from the source cluster
- kubectl access to both source and destination clusters

## Backup Process

### 0. Set Namespace Context

```bash
# Set the namespace for all subsequent commands
kubectl config set-context --current --namespace=vault
```

### 1. Create Backup

Access the Vault pod and create a backup of the data directory:

```bash
# Get into the Vault pod
kubectl exec -it vault-0 -- sh

# Create backup (write to /tmp to avoid permission issues)
tar -czf /tmp/vault-backup.tar.gz /vault/data

# Exit the pod
exit
```

### 2. Copy Backup Locally

```bash
kubectl cp vault-0:/tmp/vault-backup.tar.gz ./vault-backup.tar.gz
```

## Restore Process

### 0. Set Namespace Context

```bash
# Set the namespace for all subsequent commands
kubectl config set-context --current --namespace=vault
```

### 1. Prepare Destination Cluster

Create a PVC and helper pod to upload the backup:

```bash
# Create PVC for restore
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: vault-restore
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
EOF
```

```bash
# Create helper pod
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: vault-restore-helper
spec:
  containers:
  - name: helper
    image: busybox
    command: ['sleep', '3600']
    volumeMounts:
    - name: restore
      mountPath: /restore
  volumes:
  - name: restore
    persistentVolumeClaim:
      claimName: vault-restore
EOF
```

### 2. Upload Backup

```bash
# Wait for pod to be ready
kubectl wait --for=condition=ready pod/vault-restore-helper

# Copy backup to PVC
kubectl cp vault-backup.tar.gz vault-restore-helper:/restore/

# Verify
kubectl exec -it vault-restore-helper -- ls -lh /restore/
```

### 3. Scale Down Vault

```bash
kubectl scale statefulset vault --replicas=0

# Wait for pods to terminate
kubectl get pods -w
```

### 4. Run Restore Job

```bash
cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: vault-restore-job
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: restore
        image: busybox
        command:
        - sh
        - -c
        - |
          echo "Clearing existing data..."
          rm -rf /vault/data/*
          echo "Extracting backup..."
          tar -xzf /restore/vault-backup.tar.gz -C /
          echo "Restore complete!"
          ls -la /vault/data
        volumeMounts:
        - name: vault-data
          mountPath: /vault/data
        - name: restore
          mountPath: /restore
      volumes:
      - name: vault-data
        persistentVolumeClaim:
          claimName: data-vault-0  # Adjust to match your StatefulSet PVC name
      - name: restore
        persistentVolumeClaim:
          claimName: vault-restore
EOF
```

### 5. Monitor Restore

```bash
kubectl logs -f job/vault-restore-job
```

Wait for "Restore complete!" message.

### 6. Scale Vault Back Up

```bash
kubectl scale statefulset vault --replicas=1

# Watch it start
kubectl get pods -w
```

### 7. Unseal Vault

**Important:** Use the unseal keys from the SOURCE cluster, not the destination cluster.

```bash
# Check status (should show "Sealed: true")
kubectl exec -it vault-0 -- vault status

# Unseal (repeat 3 times with different keys)
kubectl exec -it vault-0 -- vault operator unseal
# Enter unseal key 1

kubectl exec -it vault-0 -- vault operator unseal
# Enter unseal key 2

kubectl exec -it vault-0 -- vault operator unseal
# Enter unseal key 3
```

### 8. Verify Restore

```bash
# Check status (should show "Sealed: false")
kubectl exec -it vault-0 -- vault status

# Login with root token from source cluster
kubectl exec -it vault-0 -- vault login

# Verify secrets are accessible
kubectl exec -it vault-0 -- vault secrets list
kubectl exec -it vault-0 -- vault kv list secret/
```

### 9. Cleanup

Once the restore is verified and working, clean up the temporary resources:

```bash
kubectl delete job vault-restore-job
kubectl delete pod vault-restore-helper
kubectl delete pvc vault-restore
```

## Troubleshooting

### Permission Denied During Backup

If you get "Permission denied" when creating the backup, write to `/tmp`:

```bash
tar -czf /tmp/vault-backup.tar.gz /vault/data
```

### Wrong PVC Name

If the restore job fails to find the vault data PVC, check your StatefulSet:

```bash
kubectl get pvc
kubectl describe statefulset vault | grep -A 5 volumeClaimTemplates
```

Update the `claimName` in the restore job accordingly (e.g., `data-vault-0`, `vault-data-vault-0`, etc.).

### Vault Won't Unseal

Ensure you're using the unseal keys from the **source** cluster. The backup contains encrypted data that can only be unsealed with the original keys.

## Notes

- **Storage Backend:** This guide is for Vault using file storage backend. For Raft storage, use `vault operator raft snapshot` instead.
- **Unseal Keys:** Always keep your unseal keys secure and backed up separately from the data backup.
- **Root Token:** The root token from the source cluster will work on the restored cluster.
- **High Availability:** For HA setups, restore to one node first, then join additional nodes.

## Security Considerations

- Store backups encrypted at rest
- Limit access to backup files
- Store unseal keys separately from backups
- Use proper RBAC for kubectl access
- Consider using Vault's auto-unseal feature with a KMS
