# Chapter 3: Managing Disk Images Without Slowing the Swarm

## Hook

Your component governance pipeline did its job. It scanned the dependencies, applied the organization's policies, built an OCI-compatible image, and pushed an approved artifact to Azure Container Registry. That image can now move into AKS, Azure Container Apps, or another approved runtime.

Then an agent asks for a sandbox.

Azure Container Apps Sandboxes give that agent an isolated microVM-style execution boundary, sub-second startup, default-deny egress controls, and snapshot capabilities. But the sandbox cannot start directly from the application image in ACR. The OCI image must first become a custom sandbox disk image. That conversion can take tens of seconds, depending on image size, so doing it after a user submits work gives away the startup advantage you built the platform to deliver.

The fix is to move conversion out of the request path. Let CI/CD publish the governed container image. Let the orchestrator detect that artifact, prepare the corresponding disk image in the background, and reuse it until the source content changes.

**Who This Is For:** platform teams building enterprise agent runtimes from governed images in private registries.

## What It Is

A custom sandbox disk image is the bootable form of an OCI-compatible application image for ACA Sandboxes. In this sample, the orchestrator resolves the current ACR manifest digest, looks for a `Ready` disk image labeled with that digest, and creates a new disk image only when no match exists. Once ready, that disk image becomes the immutable base for every research sandbox in the swarm.

## The Details

### 1. Convert Before the Agent Arrives

The application image belongs in the normal software supply chain. The [`azure.yaml`](../Agent-Swarm-ACA-Sandboxes/azure.yaml) post-provision hook uses Azure Container Registry Tasks to build and push `research-agent:latest`. The image already contains the agent code, Python packages, framework dependencies, and runtime server.

The orchestrator then starts disk preparation from its FastAPI lifespan hook. It creates a background task instead of blocking application initialization:

```python
if os.environ.get("DISK_IMAGE_PREWARM", "true").lower() in ("1", "true", "yes"):
    app.state.prewarm_task = asyncio.create_task(
        _prewarm_disk_image(app.state.sandbox_mgr)
    )
```

That split keeps ownership clear:

- CI/CD produces and governs the OCI image.
- ACR stores the approved artifact.
- The orchestrator converts the artifact into a sandbox disk image.
- Request-time workers start from the prepared disk image.

The sample allows up to four minutes for conversion, polling every two seconds until the image reaches `Ready`. Its infrastructure notes describe approximately 25 seconds for the current image. Those values are implementation details, not platform guarantees. Image size, layers, registry location, and service conditions can all affect preparation time.

| Conversion in the request path | Background preparation |
|---|---|
| User waits for image conversion | Application can initialize while conversion runs |
| Every restart risks repeated work | A prepared image persists across runs |
| A moving tag can hide stale content | The OCI digest identifies the exact artifact |

### 2. Treat the Digest as the Version

Tags are convenient names. They are not immutable identities. `research-agent:latest` can point to different content after every pipeline run, so the orchestrator resolves the tag to the registry's `Docker-Content-Digest` value.

The disk image receives three labels in [`sandbox_manager.py`](../Agent-Swarm-ACA-Sandboxes/orchestrator/sandbox_manager.py):

```python
labels = {
    "demo": "agents",
    "image-ref": self.container_image,
    "oci-digest": current_digest,
}
```

On startup, the manager lists existing disk images and reuses one only when all three checks pass:

- The `image-ref` label matches the configured ACR repository and tag.
- The disk image state is `Ready`.
- The stored `oci-digest` matches the digest currently returned by ACR.

A match means immediate reuse. A mismatch means the governed artifact changed, so the manager creates a new disk image and waits for it to become ready. After selecting the current image, it deletes stale images for the same source reference in a background task.

This is change detection without another deployment database. ACR remains the source of truth. The digest becomes the cache key. The same pattern also supports an event-driven design where a registry event or deployment pipeline asks the orchestrator to prepare a new image before traffic shifts to it.

### 3. Keep the Artifact Private, Then Prewarm the Runtime

The enterprise path should not require a public registry or a long-lived registry password. The Bicep template creates a user-assigned managed identity for the sandbox group, grants it `AcrPull`, and registers that identity in the sandbox group's image registry configuration. The disk manager also contains a managed identity branch for image creation.

The current deployed sample still injects ACR admin credentials into the orchestrator, and those credentials take precedence in the code. Moving to a managed-identity-only pull requires removing that fallback and validating the current preview API in the target environment.

The production deployment can place the orchestrator, sandbox group, and ACR access path inside the organization's private VNet and use managed identity for disk-image conversion. This repository does not configure private endpoints or VNet integration, so validate the networking design against the target ACA Sandboxes preview release.

A prepared disk image removes image conversion from sandbox creation. A snapshot can take the optimization one step further. Start one sandbox from the custom disk image, initialize expensive packages or agent services, verify readiness, and capture its state. New sandboxes can then be created from that snapshot instead of repeating the initialization sequence.

```bash
aca sandbox snapshot --id "$SANDBOX_ID" --name research-agent-ready
aca sandbox create --snapshot research-agent-ready
```

Snapshot creation preserves the disk and memory state required to resume the prestarted agent processes in this workload. The sample does not implement snapshot creation or snapshot-based workers today, so verify process behavior, token lifetime, trace context, and snapshot freshness before adopting this path.

Disk images and snapshots solve different problems. The disk image binds a sandbox base to a governed OCI digest. The snapshot captures a prepared runtime state derived from that base. Track both relationships so a new OCI digest invalidates not only the old disk image, but every snapshot created from it.

## Next Steps

1. **Try it:** Deploy the sample with `azd up`, push a new `research-agent:latest`, and watch the orchestrator replace the cached disk image when the ACR digest changes.
2. **Learn more:** Review the [disk-image manager](../Agent-Swarm-ACA-Sandboxes/orchestrator/sandbox_manager.py) and the [infrastructure identity assignments](../Agent-Swarm-ACA-Sandboxes/infra/main.bicep).
3. **Go deeper:** Add a snapshot preparation stage keyed to the OCI digest, then measure cold disk-image startup against snapshot-based startup in your own workload.