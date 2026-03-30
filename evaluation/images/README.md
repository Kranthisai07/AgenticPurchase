Place your evaluation images in this directory.

Guidelines
- Use the filenames referenced in `evaluation/dataset.yaml`, or update the YAML to point to your actual file names.
- Supported formats: .jpg, .jpeg, .png (others may work if your Pillow installation supports them).
- Keep images reasonably sized (e.g., < 2–4 MB) to avoid upload/latency issues during batch evaluation.

Tips
- You can maintain multiple datasets (e.g., `dataset.yaml`, `dataset_small.yaml`) that reference different image sets.
- The runner will warn with `[warn] missing image: <path>` if a file is not found.
