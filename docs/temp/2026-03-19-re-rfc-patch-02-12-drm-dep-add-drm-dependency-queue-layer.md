# Re: [RFC PATCH 02/12] drm/dep: Add DRM dependency queue layer

- Message-ID: `<20260319101153.169c7f36@fedora>`
- Classification: `rust_unsafe_bug`
- Confidence: `medium`
- Mailing list: `linux-kernel.vger.kernel.org`
- Published at: `2026-03-19T09:11:53+00:00`
- Author: `Boris Brezillon <boris.brezillon@collabora.com>`
- Archive URL: not recorded
- Source path: `data/raw/results-rust-bug.mbox::98`

## Summary

The message points to a Rust unsafe/soundness bug.

## Evidence

Subject/body signals include assume that, contract, dangling, invariant, lifetime, non-null.

## Original Subject

Re: [RFC PATCH 02/12] drm/dep: Add DRM dependency queue layer

## Body Excerpt

```text
Hi Matthew, On Wed, 18 Mar 2026 16:28:13 -0700 Matthew Brost <matthew.brost@intel.com> wrote: > > - fence must be signaled for dma_fence::ops to be set back to NULL > > - no .cleanup and no .wait implementation > > > > There might be an interest in having HW submission fences reflecting > > when the job is passed to the FW/HW queue, but that can done as a > > separate fence implementation using a different fence timeline/context. > > > > Yes, I removed scheduled side of drm sched fence as I figured that could > be implemented driver side (or as an optional API in drm dep). Only > AMDGPU / PVR use these too for ganged submissions which I need to wrap > my head around. My initial thought is both of implementations likely > could be simplified. IIRC, PVR was also relying on it to allow native FW waits: when we have a job that has deps that are backed by fences emitted by the same driver, they are detected and lowered to waits on the "scheduled" fence, the wait on the finished fence is done FW side. > > > > diff --git a/drivers/gpu/drm/dep/drm_dep_job.c b/drivers/gpu/drm/dep/drm_dep_job.c > > > new file mode 100644 > > > index 000000000000..2d012b29a5fc > > > --- /dev/null > > > +++ b/drivers/gpu/drm/dep/drm_dep_job.c > > > @@ -0,0 +1,675 @@ > > > +// SPDX-License-Identifier: MIT > > > +/* > > > + * Copyright 2015 Advanced Micro Devices, Inc. > > > + * > > > + * Permission is hereby granted, free of charge, to any person obtaining a > > > + * copy of this software and associated documentation files (the "Software"), > > > + * to deal in the Software without restriction, including without limitation > > > + * the rights to use, copy, modify, merge, publish, distribute, sublicense, > > > + * and/or sell copies of the Software, and to permit persons to whom the > > > + * Software is furnished to do so, subject to the following conditions: > > > + * > > > + * The above copyright notice and this permission notice shall be included in > > > + * all copies or substantial portions of the Software. > > > + * > > > + * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR > > > + * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, > > > + * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL > > > + * THE COPYRIGHT HOLDER(S) OR AUTHOR(S) BE LIABLE FOR ANY CLAIM, DAMAGES OR > > > + * OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, > > > + * ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR > > > + * OTHER DEALINGS IN THE SOFTWARE. > > > + * > > > + * Copyright © 2026 Intel Corporation > > > + */ > > > + > > > +/** > > > + * DOC: DRM dependency job > > > + * > > > + * A struct drm_dep_job represents a single unit of GPU work associated with > > > + * a struct drm_dep_queue. The lifecycle of a job is: > > > + * > > > + * 1. **Allocation**: the driver allocates memory for the job (typically by > > > + * embedding struct drm_dep_job in a larger structure) and calls > > > + * drm_dep_job_init() to initialise it. On success the job holds one > > > + * kref reference and a reference to its queue. > > > + * > > > + * 2. **Dependency collection**: the driver calls drm_dep_job_add_dependency(), > > > + * drm_dep_job_add_syncobj_dependency(), drm_dep_job_add_resv_dependencies(), > > > + * or drm_dep_job_add_implicit_dependencies() to register dma_fence objects > > > + * that must be signalled before the job can run. Duplicate fences from the > > > + * same fence context are deduplicated automatically. > > > + * > > > + * 3. **Arming**: drm_dep_job_arm() initialises the job's finished fence, > > > + * consuming a sequence number from the queue. After arming, > > > + * drm_dep_job_finished_fence() returns a valid fence that may be passed to > > > + * userspace or used as a dependency by other jobs. > > > + * > > > + * 4. **Submission**: drm_dep_job_push() submits the job to the queue. The > > > + * queue takes a reference that it holds until the job'
```
