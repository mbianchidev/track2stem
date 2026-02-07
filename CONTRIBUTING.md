# Contributing to Track2stem

Thank you for your interest in contributing to Track2stem! This document provides guidelines and instructions for contributing.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/track2stem.git`
3. Create a new branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test your changes thoroughly
6. Commit your changes: `git commit -m "Add your feature"`
7. Push to your fork: `git push origin feature/your-feature-name`
8. Create a Pull Request

## Development Setup

### Prerequisites

- Docker and Docker Compose
- Go 1.21+ (for backend development)
- Node.js 18+ (for frontend development)
- Python 3.13+ (for processor development)

### Running Locally

```bash
# Start all services
make up

# Or with logs
make dev

# View logs
make logs
```

## Project Structure

```
track2stem/
├── backend/          # Go backend API
│   ├── main.go
│   ├── go.mod
│   └── Dockerfile
├── frontend/         # React frontend
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── Dockerfile
├── processor/        # Python audio processor
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
└── docker-compose.yml
```

## Coding Standards

### Backend (Go)

- Follow standard Go formatting (`gofmt`)
- Use meaningful variable and function names
- Add comments for exported functions
- Handle errors appropriately
- Write tests for new functionality

### Frontend (React)

- Use functional components and hooks
- Follow ESLint configuration
- Use meaningful component and variable names
- Keep components focused and reusable
- Add PropTypes or TypeScript types

### Processor (Python)

- Follow PEP 8 style guide
- Use type hints where appropriate
- Add docstrings for functions
- Handle exceptions properly
- Write tests for new functionality

## Testing

### Backend Tests

```bash
cd backend
go test ./...
```

### Frontend Tests

```bash
cd frontend
npm test
```

### Integration Tests

Before submitting a PR, test the full workflow:
1. Upload a sample audio file
2. Verify processing completes successfully
3. Download and verify all stems
4. Check for errors in logs

## Pull Request Process

1. Update the README.md with details of changes if applicable
2. Update documentation for any API changes
3. Ensure all tests pass
4. Ensure Docker builds succeed
5. Get approval from maintainers

## Code Review Process

All submissions require review. We use GitHub pull requests for this purpose.

## Reporting Issues

When reporting issues, please include:

- Clear description of the problem
- Steps to reproduce
- Expected behavior
- Actual behavior
- System information (OS, Docker version, etc.)
- Relevant logs

## Feature Requests

We welcome feature requests! Please:

- Check if the feature has already been requested
- Provide a clear use case
- Explain why this feature would be useful
- Be open to discussion

## Community

Be respectful and constructive in all interactions. We aim to maintain a welcoming and inclusive community.

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.
