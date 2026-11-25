# Contributing

Imua is a private project. This document is for internal reference.

## Repository Structure

```
imua/
├── README.md                    # Overview
├── docker-compose.yml           # Docker Compose config
├── Dockerfile                    # Container build
├── imua.yaml                     # Configuration
├── config.example.yaml           # Example config
├── app/
│   ├── server.py                # Flask application
│   ├── models.py                 # SQLite models
│   ├── templates/                # Jinja2 templates
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── agent.html
│   │   └── project.html
│   ├── static/                   # CSS, JS
│   └── skills/                   # Hermes skill files
├── docs/
│   ├── architecture.md           # System architecture
│   ├── api.md                    # API reference
│   ├── agent-integration.md      # Hermes connection guide
│   ├── setup-guide.md            # Installation
│   └── agent-personas.md         # Agent customization
├── scripts/
│   ├── post-receive              # Git hook for auto-deploy
│   └── generate-avatar.py        # Agent avatar generation
└── data/                         # Runtime data (git-ignored)
    ├── database/
    ├── repos/
    └── docs/
```

## Development Workflow

1. Make changes locally
2. Test with `docker compose up --build`
3. Commit and push to GitHub
