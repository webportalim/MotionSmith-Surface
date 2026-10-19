# MotionSmith Surface

**Free AI texturing and PBR material generation for Blender.**

Create textures for a selected mesh or extract PBR material maps from a single image, using a local ComfyUI backend.

![MotionSmith Surface documentation and material workflows](https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEhUSmqRdmdHBBqA2SxCEqOFxUPXh1UVVI3FSUoHrQtG9fbBB-yHjXBdp7y7o3KqSghJhomW14hya1wSX6hyZYb8KpS0rgYPHkTVJatftK2bOg3Zghigf9KjO7Fa7JHhf_kkNNBTgGalTVl0735PlcHmGKK7kg9czv6gWpLVIHf3o6WiGJkYXBgJNLmLNdrv/s1600/docs-hero.png)

Created by **Sertan Koç — OneManStudio**.

[Download the add-on](https://github.com/webportalim/MotionSmith-Surface/raw/refs/heads/main/motionsmith_surface.zip) · [Documentation](https://motionsmithai.blogspot.com/p/motionsmith-surface-docs.html) · [Product page](https://motionsmithai.blogspot.com/p/motionsmith-surface.html) · [Backend files](https://huggingface.co/Serqan/MotionSmith-Runtime/tree/main/blender/MotionSmith-Surface)

## Install

1. Download **[motionsmith_surface.zip](https://github.com/webportalim/MotionSmith-Surface/raw/refs/heads/main/motionsmith_surface.zip)**. Keep it zipped.
2. In Blender, open **Edit → Preferences → Add-ons → Install from Disk**, select the ZIP and enable **MotionSmith Surface**.
3. Expand the add-on preferences and click **Install** under **Backend & Models Setup**.
4. Follow the setup window. It searches for existing ComfyUI installations, suggests an installation folder, and downloads missing files.
5. After setup, enter the displayed **ComfyUI Directory** in the **Backend** preferences. Check the **Python Executable** path; selecting a backend with `.venv` fills it automatically. Save Preferences.
6. Open the 3D Viewport sidebar with **N → Surface**, start the server and wait for **Online**.

The installer is bundled inside the add-on. You can also run [install_motionsmith_surface.bat](install_motionsmith_surface.bat) directly.

### Existing ComfyUI and models

- Setup searches local fixed disks for ComfyUI installations, excluding system folders, Python environments and other bulky dependency folders.
- If an installation has a recognized Python environment and the four required Surface node folders, it can be reused. Otherwise, setup installs a separate Surface backend instead of overwriting the existing installation.
- Setup checks discovered model folders and paths configured in `extra_model_paths.yaml`.
- Existing weights are matched by file size and **SHA-256**, including files with different names. Valid models are reused with hard links where possible; otherwise they are copied locally.
- Only missing weights are downloaded. Interrupted downloads can resume, and existing destination files are verified before being skipped.

The full backend-and-model download is approximately **21.5 GiB** if nothing is installed. Allow at least **35 GiB of free disk space** for a fresh setup. The backend ZIP itself contains no model weights.

**Chord access:** the PBR model may require you to sign in to Hugging Face and accept its terms. Setup displays the model page and can request a hidden Read token. The token is not written to a file. You may skip Chord and finish the Texture setup first.

## Two workflows

| Mode | Input | Result |
| --- | --- | --- |
| **Texture** | A selected mesh, with text and/or an image reference | Generated views, UV baking and material assignment |
| **PBR Material** | One image | Base Color, Normal, Roughness, Metallic and Height maps |

Generation runs through your local ComfyUI backend. Generated texture images are packed into the `.blend` file; save the blend file to retain them.

## Panel guide

The sections below follow the add-on from top to bottom. Screenshots show the controls available at the time of capture; some fields change with the selected workflow.

### 1. Server and target mesh

![Server controls, page tabs and Target Mesh](https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEj2sWpiuYGQnRqymNer1j-TjOu4Ilq-1WYQGxpl7WBv1Y8ps0vri1Nk56Plno6KhrL6oIlBpJeSIYk3JMFFL2sDkCq28q3wFAUzQYoln73b_oSEIYpflaW_1P53gmdLAMghjPbqtbV1QOl0izIpFykK6w_ms-9cZO3aLTltIZYGU54iCQdfc80NZlJde5UG/s1600/Ekran%20g%C3%B6r%C3%BCnt%C3%BCs%C3%BC%202026-10-19%20102115.png)

Click **Start Server** and wait for **Online**. The refresh button checks the connection; the browser button opens ComfyUI. **Stop Server** shuts down the backend.

Choose **Texture** or **PBR Material**. For Texture generation, select the intended mesh in the viewport and check its name under **Target Mesh**.

### 2. Texture Workflow

![Texture Workflow options](https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEhJ8ruPdh13N_xiknDARLrEruKQqrCT3955YPKlH6lvOa6QMBE8Yz3dfeys8kl8u9yIpf8jqOTAJ2yjFF_PXVmnXhaH8ChJ8nwDK07WOw9e1kk37UETjbXOt33zij6jwLfdyayzujPw0_ATCcVFKd7HgXKArTvJjQejck-qiNL37Y7eDIjGe_RVWulaxLMV/s1600/Ekran%20g%C3%B6r%C3%BCnt%C3%BCs%C3%BC%202026-10-19%20102154.png)

| Workflow | Behavior |
| --- | --- |
| **6 Views — 1 Pass** | Generates six canonical views. A practical starting point. |
| **10 Views — 2 Pass** | Six views followed by four diagonal refinement views. Uses one appearance reference in image-guided modes. |
| **10 Views — Manual Camera Inputs** | Uses ten supplied camera views, from Blender renders, a folder or individual files. Bakes captured albedo and optionally predicts metallic/roughness. |
| **Low VRAM — GGUF** | Modular generation and baking with quantized models and additional view/decode settings. |

**Pass 2 Denoise** controls how strongly the diagonal pass changes the first-pass result. More views and higher resolutions increase processing time; they do not guarantee a better bake.

### 3. Camera & Capture Setup

![Camera and capture controls](https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEhXbLlubGFS-gsWd6V3t3aobaPGbiARSB0owg6PGSMsJnOUIsI0Y8ZHHAVrY_7QusJTr9arNTBpU8WBBj7yytPhO873nUeWanycGGFOkovFA45yGPuSnupIhIc2WLespu1J3q_6kXsczxVkZ_ofD0_qMcHqYJ3fmyi84Gz3ruDiozo0eOUzxdoMGwsvd5Jk/s1600/Ekran%20g%C3%B6r%C3%BCnt%C3%BCs%C3%BC%202026-10-19%20102204.png)

For the standard image-guided workflows, **Setup Camera (1 Cam)** frames the mesh with a calibrated front camera. **View Camera** lets you check the framing.

If no **Reference Image** file is selected, the workflow uses the front-camera capture. When a reference file is selected, that file supplies the appearance reference. **Prompt Only** skips image capture. The manual ten-view workflow shows its own camera/photo controls instead.

### 4. Generation Inputs

![Generation input modes, prompts, reference image and Generate Texture](https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEg3FbZQpdbnCe6vHTP3bAtUiKjEzbk6Se6reXjkPZ93WVdexgVnbmrMW-rFLOTT_2xYvLtAS4l65IOuxwyPV7lR0UCh4bNGzzcSJjdOmrqrd8bki4eLqAIqxa0hF7O0dvQ8WVv1lFEuEH-pVMLxRp9nZbcUNwrqGadr7usk2UR-JJgo9wYJlLnxlZo4rP3Z/s1600/Ekran%20g%C3%B6r%C3%BCnt%C3%BCs%C3%BC%202026-10-19%20102218.png)

- **Prompt Only:** use text and mesh geometry without an appearance-reference image.
- **Image Only:** use an image or camera capture; text prompts are not sent.
- **Prompt + Image:** combine both sources of guidance.
- **Preset:** optional. Keep **No Preset / Custom** to use your own prompt. A material preset replaces the positive prompt with its material description.
- **Positive Prompt:** the default asks the model to preserve the reference colors, patterns and surface details. Edit it to request a deliberate change.
- **Enable Negative Prompt / CFG:** enables separate negative conditioning and uses additional compute and VRAM.
- **Reference Image:** choose a file, or leave it empty to use the front-camera capture in image-guided modes.

Click **Generate Texture** to submit the job. **Cancel** appears during generation. **Check / Apply Last Result** checks the latest job and applies a completed result without starting another generation.

The status area reports the active operation. Progress and estimated time remaining, when available, apply to the **current stage**, not the entire workflow.

### 5. Model Selection

![Texture model selection](https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEhS1gRUu6n6JJg9J9kwBUHd212_AEYNL-9qV4uuvgN-sm14fku6fECpv1u1JnlsJbqR1Kz4EZWaUcgLJfSM819JFBU4DmEehx71k9KGS7xL6zYVkhA7xFUODs_5yb-JA5EFCyFPZkv25_brlzDjC_kmH_9gKE8A7aKonKWy4_LD0-hzflfq04FFYYd5QlVP/s1600/Ekran%20g%C3%B6r%C3%BCnt%C3%BCs%C3%BC%202026-10-19%20102233.png)

Select the installed diffusion model, text encoder, VAE, UltraTex decoder, Albedo LoRA, Metallic/Roughness LoRA and background-removal model. Refresh the list after adding models.

In **Preferences → Models**, the add-on shows which required files are installed or missing. Use the main **Install** button for setup.

### 6. Workflow Parameters

![Sampling, resolution, UV and material parameters](https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEia3aSjVz6LoxlN3UGOFpiOFhufooEt-4ePB9MFfr3_TDpRMW__Myuo0vSMzcxs6hFvP_y1uHeDqEpIlrjYmcQYxlMrW60r5gXGQOK7YNFlsvdZnKsXsXXElT7yuSHxvF_QbHbN9Hw85Oh9Fgz44ShxDr1cczpffgBioJfpa-hYiHIbreoBlPQtUQ0NS0Oh/s1600/Ekran%20g%C3%B6r%C3%BCnt%C3%BCs%C3%BC%202026-10-19%20102248.png)

| Setting | Purpose |
| --- | --- |
| **Albedo Steps / Guidance / Seed** | Control sampling and text guidance. Keep the seed fixed when comparing settings. |
| **View Resolution** | Resolution per view; higher values increase processing time and memory use. |
| **Generate Metallic / Roughness** | Enables the additional MR prediction pass, with its own steps and resolution. |
| **Texture Size** | Resolution of the final baked UV maps. |
| **UV Mode** | Choose Comfy GPU, xatlas or Keep Existing UVs. |
| **Material Slot Policy** | Apply across the mesh, replace the active slot, or append a new slot. |
| **Geometry Render Size / Alignment** | Control geometry projection and reference placement in standard workflows. |

Low VRAM workflows expose additional generated-view and UV-padding controls. Start with lower settings to check the workflow before increasing quality.

### 7. Advanced Tuning

![Advanced LoRA, attention and baking settings](https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEgBDp7axZRIGbGzvS962Y9y2l_UEOaeuFIrbofM8XjR556xoT__tCRGKa-SfHbANg52BvtDAffS4CpPNjkemJCIsceayng1s5JeAZ6RsqrrF8lfdiOxc3BGAbBoS7bUzGJAmXntl33kFgobFxTPAvopgzuuCSI5vGlB-adanFARuZheEQjoeYHhwQgH_DLj/s1600/Ekran%20g%C3%B6r%C3%BCnt%C3%BCs%C3%BC%202026-10-19%20102310.png)

Tune LoRA strengths, attention, sparse retention, memory reservation, reprojection and bake blending. Available settings depend on the workflow.

The GGUF workflow also exposes tiled decode, unseen-surface filling/repair and extra-angle settings. Start with defaults and change one setting at a time. See the [full documentation](https://motionsmithai.blogspot.com/p/motionsmith-surface-docs.html#advanced) for field descriptions.

### 8. PBR Material

![PBR Material image input and generation controls](https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEj0hWtyUlgWxOZgGnAhfBmNrgoaKaeIE64vVPjofsJGyq3OCxCBAgzQOiqedEZ5G5TEv97lEVGEObd-yiWShtlNsd4_7LwtDQT-ICDnVufKchQn8FrWPmaYjKEC-T-r-Af9BKri9vOAj3boM8GLxtcQZbWH9O3xhFWlZn_LB9uF9qWiPsF3aXIfiqImDRR8/s1600/image.png)

Switch to **PBR Material**, select an **Image**, and click **Generate PBR Material**. This mode uses the Chord image-to-material workflow without Texture presets, text prompts or camera setup.

Select a mesh in **Object Mode** with an active UV map before generating to apply the result to its active material slot. Without a suitable mesh, the material is created in Blender’s material list for manual assignment.

The **Height** map is retained as a texture node; displacement is not connected automatically. Cancel and result recovery work here too.

## Requirements

- **Blender 5.0+**, tested with Blender 5.2.
- **Windows 64-bit** for the supplied installer and backend.
- An **NVIDIA GPU** compatible with the bundled CUDA/PyTorch runtime. Memory requirements vary by workflow, model and resolution; testing used an RTX 5070 Ti with 16 GB VRAM.
- Internet access for initial downloads; model publishers may require account access or license acceptance.

The supplied backend was assembled with ComfyUI 0.27.0, Python 3.12.10 and PyTorch 2.8.0 + CUDA 12.8. It includes the UltraTex, modular UltraTex, Chord and GGUF node packages. Backend binaries and model weights are distributed separately from this source repository.

## Repository

```text
addon/motionsmith_surface/         Blender add-on source, workflows and bundled installer
motionsmith_surface.zip            Installable Blender add-on
install_motionsmith_surface.bat    Standalone backend/model installer
package_addon.py                   Rebuild the add-on ZIP
```

To rebuild the ZIP from source:

```sh
python package_addon.py
```

## License and credits

MotionSmith Surface is free and the add-on is distributed under **GPL-3.0-or-later**, as declared in its Blender manifest. See [LICENSE](LICENSE).

Third-party runtimes, nodes, models and bundled dependencies retain their own licenses. In particular, **Chord uses the Ubisoft Machine Learning Research-Only license**; a free add-on does not grant commercial rights to research-only models. Check each model’s terms for your intended use.

Powered by [ComfyUI](https://github.com/comfyanonymous/ComfyUI), UltraTex, GGUF support and [Ubisoft Chord](https://huggingface.co/Ubisoft/ubisoft-laforge-chord).

**Sertan Koç — OneManStudio** · [More MotionSmith tools](https://motionsmithai.blogspot.com/)
