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

See the [development guide](docs/development.md) for toolchain versions, local execution, architecture, tests, and builds. The [documentation index](docs/README.md) links usage, configuration, and API references.

Coding agents must read [AGENTS.md](AGENTS.md) before editing. All contributors remain accountable for their work under the [AI policy](README.md#ai-policy).

## Coding Standards

### Backend (Go)

- Follow standard Go formatting (`gofmt`)
- Use meaningful variable and function names
- Add comments for exported functions
- Handle errors appropriately
- Write tests for new functionality

### Frontend (React)

- Use functional components and hooks
- Follow the existing component formatting and patterns
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

Run the relevant [development checks](docs/development.md), matching the [CI workflow](.github/workflows/ci.yml). Use synthetic audio and mock data only.

### Integration Tests

For processing changes, test the full workflow before submitting a PR:

1. Upload a generated audio file
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
