# [PATCH v6 2/5] rust/drm: Introduce DeviceContext

- Message-ID: `<20260320233645.950190-3-lyude@redhat.com>`
- Classification: `rust_unsafe_bug`
- Confidence: `medium`
- Mailing list: `nouveau.lists.freedesktop.org`
- Published at: `2026-03-20T23:34:27+00:00`
- Author: `Lyude Paul <lyude@redhat.com>`
- Archive URL: not recorded
- Source path: `data/raw/results-rust-bug.mbox::75`

## Summary

The message points to a Rust unsafe/soundness bug.

## Evidence

Subject/body signals include invariant, lifetime, non-null, nonnull, ownership, ub.

## Original Subject

[PATCH v6 2/5] rust/drm: Introduce DeviceContext

## Body Excerpt

```text
One of the tricky things about DRM bindings in Rust is the fact that initialization of a DRM device is a multi-step process. It's quite normal for a device driver to start making use of its DRM device for tasks like creating GEM objects before userspace registration happens. This is an issue in rust though, since prior to userspace registration the device is only partly initialized. This means there's a plethora of DRM device operations we can't yet expose without opening up the door to UB if the DRM device in question isn't yet registered. Additionally, this isn't something we can reliably check at runtime. And even if we could, performing an operation which requires the device be registered when the device isn't actually registered is a programmer bug, meaning there's no real way to gracefully handle such a mistake at runtime. And even if that wasn't the case, it would be horrendously annoying and noisy to have to check if a device is registered constantly throughout a driver. In order to solve this, we first take inspiration from `kernel::device::DeviceContext` and introduce `kernel::drm::DeviceContext`. This provides us with a ZST type that we can generalize over to represent contexts where a device is known to have been registered with userspace at some point in time (`Registered`), along with contexts where we can't make such a guarantee (`Uninit`). It's important to note we intentionally do not provide a `DeviceContext` which represents an unregistered device. This is because there's no reasonable way to guarantee that a device with long-living references to itself will not be registered eventually with userspace. Instead, we provide a new-type for this: `UnregisteredDevice` which can provide a guarantee that the `Device` has never been registered with userspace. To ensure this, we modify `Registration` so that creating a new `Registration` requires passing ownership of an `UnregisteredDevice`. Signed-off-by: Lyude Paul <lyude@redhat.com> Reviewed-by: Daniel Almeida <daniel.almeida@collabora.com> --- V2: * Make sure that `UnregisteredDevice` is not thread-safe (since DRM device initialization is also not thread-safe) * Rename from AnyCtx to Uninit, I think this name actually makes a bit more sense. * Change assume_registered() to assume_ctx() Since it looks like in some situations, we'll want to update the DeviceContext of a object to the latest DeviceContext we know the Device to be in. * Rename Init to Uninit When we eventually add KMS support, we're going to have 3 different DeviceContexts - Uninit, Init, Registered. Additionally, aside from not being registered there are a number of portions of the rest of the Device which also aren't usable before at least the Init context - so the naming of Uninit makes this a little clearer. * s/DeviceContext/DeviceContext/ For consistency with the rest of the kernel * Drop as_ref::<Device<T, Uninit>>() for now since I don't actually think we need this quite yet V3: * Get rid of drm_dev_ctx!, as we don't actually need to implement Send or Sync ourselves * Remove mention of C function in drm::device::Registration rustdoc * Add more documentation to the DeviceContext trait, go into detail about the various setup phases and such. * Add missing period to comment in `UnregisteredDevice::new()`. V4: * Address some comments from Danilo I missed last round: * Remove leftover rebase detritus from new_foreign_owned() (the seemingly useless cast) * Remove no-op mention in Registered device context V5: * Fix incorrect size on Kmalloc (Deborah) drivers/gpu/drm/nova/driver.rs | 8 +- drivers/gpu/drm/tyr/driver.rs | 10 +- rust/kernel/drm/device.rs | 191 +++++++++++++++++++++++++++------ rust/kernel/drm/driver.rs | 35 ++++-- rust/kernel/drm/mod.rs | 4 + 5 files changed, 197 insertions(+), 51 deletions(-) diff --git a/drivers/gpu/drm/nova/driver.rs b/drivers/gpu/drm/nova/driver.rs index b1af0a099551d..99d6841b69cbc 100644 --- a/drivers/gpu/drm/nova/driver.rs +++ b/drivers/gpu/drm/nova/driver.rs @@
```
