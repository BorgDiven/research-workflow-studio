# Public website

The product homepage is Chinese by default, with an English page at `en/`. The embedded desktop demo reuses the workbench UI and an independent fictional project. The demo interface is currently Chinese.

Build the website from the repository root:

```sh
python3 tools/build_site.py --output .local/public-site
python3 -m http.server 8837 --bind 127.0.0.1 --directory .local/public-site
```

Open `http://127.0.0.1:8837/`. The static output can also be hosted under a path such as `/research-workflow-studio/`.

The build creates a fresh temporary database from `tools/seed_showcase.py`, exports the fictional records and context, and copies only public website resources. It does not accept a production database. Database files are not included in the website.

Visitors can select nodes, focus a region, switch views, filter comparisons, and inspect evidence and frozen reports. The demo does not save server records, connect to an AI client, or execute experiments. The installed application keeps its normal backend and MCP behavior.

The `Public website` GitHub Actions workflow tests, builds, and deploys the static output to GitHub Pages when relevant files on `main` change. Pages must use GitHub Actions as its publishing source. No custom domain is required.
