# Catalog notebooks

Colab is not a host we deploy to. It **opens this git file over HTTPS**.  
Push the notebook → the next person who clicks the GitHub Colab URL gets that commit.

## Open (always latest `main`)

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/tmai-tech/Makeo/blob/explore-catalog-vton/notebooks/fashn_vton_colab.ipynb)

- GitHub → Colab: https://colab.research.google.com/github/tmai-tech/Makeo/blob/explore-catalog-vton/notebooks/fashn_vton_colab.ipynb
- Short link (Pages): https://tmai-tech.github.io/Makeo/colab/fashn-vton/

A branch or SHA works the same way:

```
https://colab.research.google.com/github/tmai-tech/Makeo/blob/<branch-or-sha>/notebooks/fashn_vton_colab.ipynb
```

## Do not

- **File → Save a copy in Drive** as the working copy. That file never sees `git push`.
- Expect GitHub Actions to “update Colab.” There is no Colab upload API for this. The Action only **validates** the `.ipynb` and prints the URL.

## Catalog page + background Colab

1. Open Colab from Makeo → **Catalog** → Start Colab. T4, Run all, then run **Start worker**.
2. Copy the `trycloudflare.com` URL into Catalog → Save. The pill should say **Colab worker live**.
3. Stay on Makeo. Drop a model + garment → **Create look** (1–3 min).
4. Leave the Colab tab open. The last cell must keep running.

## From the Makeo generator

Generate → **Start Colab** opens this notebook in a **new tab**. Makeo stays put.

Google will **not** run cells by itself (no URL can start a T4). In the Colab tab the user does **Runtime → T4** then **Runtime → Run all**, then goes back to Makeo while weights download.

## Workflow

1. Edit `notebooks/fashn_vton_colab.ipynb`.
2. `python notebooks/check_notebook.py`
3. Commit and push.
4. Re-open the GitHub Colab URL (refresh if a tab was already open **from GitHub**, not from Drive).
5. Runtime → **T4 GPU**.

CI: `.github/workflows/notebooks.yml` runs the checker on every change under `notebooks/`.

## Better than Colab if the goal is “push and it just works”

| Goal | Use |
|---|---|
| Lab / T4 / our cells | This notebook via the GitHub URL |
| Public demo that rebuilds on push | A Hugging Face Space pointed at this repo (real deploy, ZeroGPU queue) |
| Readable diffs | Pair the notebook with [Jupytext](https://jupytext.readthedocs.io/) later — not required to launch Colab |

The official Space is already live: https://huggingface.co/spaces/fashn-ai/fashn-vton-1.5  
IDM-VTON (browser only, **non-commercial**): https://huggingface.co/spaces/yisol/IDM-VTON
