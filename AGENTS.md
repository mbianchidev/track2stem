# AGENTS.md - AI Coding Agent Guide for track2stem

## 📋 Project Overview

**track2stem** is an audio processing tool designed to convert single audio tracks into multi-stem outputs (separating vocals, drums, bass, and other instruments). This guide provides comprehensive information for AI coding agents working on this codebase.

### Project Purpose
- Convert single audio tracks into multiple separate stems (vocals, drums, bass, instruments)
- Leverage audio source separation technology
- Provide an accessible interface for audio stem separation

### Current Project Status
⚠️ **Note**: This is a newly initialized repository. The codebase is currently in early development stages with minimal implementation.

---

## 📁 Project Structure

### Current Repository Layout

```
track2stem/
├── README.md           # Project description
├── LICENSE            # MIT License
├── AGENTS.md          # This file - AI agent guidance
└── .git/              # Git repository metadata
```

### Expected Future Structure

As the project develops, expect the following structure:

```
track2stem/
├── src/               # Main source code
│   ├── core/         # Core audio processing logic
│   ├── models/       # ML model interfaces/wrappers
│   ├── cli/          # Command-line interface
│   ├── api/          # API/web interface (if applicable)
│   └── utils/        # Utility functions
├── tests/            # Test suite
│   ├── unit/         # Unit tests
│   ├── integration/  # Integration tests
│   └── fixtures/     # Test audio files and fixtures
├── docs/             # Documentation
├── examples/         # Usage examples
├── models/           # Pre-trained model files (possibly gitignored)
├── scripts/          # Build, deployment, and utility scripts
├── requirements.txt  # Python dependencies (if Python)
├── package.json      # Node.js dependencies (if Node.js)
├── setup.py          # Python package setup (if Python library)
├── .gitignore        # Git ignore patterns
├── .github/          # GitHub workflows and configurations
│   └── workflows/    # CI/CD pipelines
├── README.md
├── LICENSE
└── AGENTS.md
```

---

## 🛠️ Tech Stack

### Expected Technologies

Based on the project's audio processing nature, expect:

#### Primary Languages
- **Python** (most likely) - dominant in audio ML/DSP
  - Libraries: librosa, pydub, scipy, numpy
  - ML frameworks: PyTorch, TensorFlow
  - Audio separation: Spleeter, Demucs, Open-Unmix
- **JavaScript/TypeScript** (possible) - for web interface
  - Frameworks: React, Vue, or Node.js backend
- **Rust** (possible) - for performance-critical audio processing

#### Audio Processing Stack
- **Demucs** - State-of-the-art music source separation
- **Spleeter** - Deezer's source separation library
- **librosa** - Audio analysis library
- **ffmpeg** - Audio/video processing
- **PyTorch/TensorFlow** - Deep learning frameworks

#### Testing & Quality
- **pytest** (Python) or **Jest** (JavaScript) - Testing frameworks
- **black** (Python) or **Prettier** (JavaScript) - Code formatting
- **pylint/flake8** (Python) or **ESLint** (JavaScript) - Linting

---

## 🧭 Navigation Guide

### Finding Different Types of Files

#### Source Code
- **Core Logic**: Look in `src/core/` or root `src/` directory
- **Models**: Check `src/models/` or `models/` for ML model code
- **CLI**: Find in `src/cli/`, `cli/`, or root scripts
- **API**: Look in `src/api/` or `api/` directory

#### Tests
- **Unit Tests**: `tests/unit/` or `test/` directory
- **Integration Tests**: `tests/integration/` or `tests/e2e/`
- **Test Fixtures**: `tests/fixtures/`, `tests/data/`, or `fixtures/`

#### Configuration Files
- **Python**: `requirements.txt`, `setup.py`, `pyproject.toml`, `setup.cfg`
- **Node.js**: `package.json`, `package-lock.json`, `tsconfig.json`
- **Docker**: `Dockerfile`, `docker-compose.yml`
- **CI/CD**: `.github/workflows/*.yml`
- **Environment**: `.env.example`, `.env.template`

#### Documentation
- **User Docs**: `docs/`, `README.md`
- **API Docs**: `docs/api/` or auto-generated from code
- **Examples**: `examples/` or `samples/` directory

---

## 📝 Coding Conventions

### General Guidelines

As the codebase develops, maintain these conventions:

#### Python (if used)
- **Style**: Follow PEP 8 guidelines
- **Formatting**: Use `black` with default settings (88 char line length)
- **Imports**: Group stdlib, third-party, and local imports separately
- **Type Hints**: Use type hints for function signatures
- **Docstrings**: Use Google or NumPy docstring format
- **Naming**:
  - Functions/variables: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_CASE`
  - Private: prefix with `_`

```python
# Example structure
from typing import Tuple

import numpy as np
import torch

from track2stem.core.audio import AudioProcessor


class StemSeparator:
    """Separates audio tracks into multiple stems."""
    
    def __init__(self, model_path: str) -> None:
        self._model = self._load_model(model_path)
    
    def separate(self, audio: np.ndarray) -> Tuple[np.ndarray, ...]:
        """Separate audio into stems.
        
        Args:
            audio: Input audio as numpy array
            
        Returns:
            Tuple of separated stems (vocals, drums, bass, other)
        """
        pass
```

#### JavaScript/TypeScript (if used)
- **Style**: Follow Airbnb or Standard JS style guide
- **Formatting**: Use Prettier with 2-space indentation
- **Naming**:
  - Functions/variables: `camelCase`
  - Classes/Components: `PascalCase`
  - Constants: `UPPER_CASE`
  - Private: prefix with `_` or use `#`
- **Imports**: Use ES6 modules
- **Types**: Use TypeScript for type safety

```typescript
// Example structure
interface StemOptions {
  modelPath: string;
  outputFormat: 'wav' | 'mp3';
}

export class StemSeparator {
  private model: Model;
  
  constructor(options: StemOptions) {
    this.model = this.loadModel(options.modelPath);
  }
  
  async separate(audioBuffer: AudioBuffer): Promise<Stem[]> {
    // Implementation
  }
}
```

#### Git Commit Messages
- Use conventional commits format: `type(scope): message`
- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
- Examples:
  - `feat(core): add Demucs model integration`
  - `fix(cli): handle missing input file error`
  - `docs: update installation instructions`

---

## 🔨 Build, Test, and Run Instructions

### Setup (Expected)

```bash
# Clone the repository
git clone https://github.com/mbianchidev/track2stem.git
cd track2stem

# Python setup (if Python-based)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -e .  # Install in development mode

# Node.js setup (if Node.js-based)
npm install
# or
yarn install
```

### Running Tests

```bash
# Python
pytest                          # Run all tests
pytest tests/unit              # Run unit tests only
pytest -v --cov=track2stem     # Run with coverage

# Node.js
npm test                        # Run all tests
npm run test:unit              # Run unit tests
npm run test:watch             # Run in watch mode
```

### Running the Application

```bash
# Python CLI
python -m track2stem input.mp3 -o output/
# or
track2stem input.mp3 -o output/

# Node.js
npm start
node dist/index.js input.mp3
```

### Building

```bash
# Python
python setup.py build
python setup.py sdist bdist_wheel

# Node.js
npm run build
# or
yarn build
```

### Linting and Formatting

```bash
# Python
black .                    # Format code
flake8 src/ tests/        # Lint code
mypy src/                 # Type checking

# Node.js
npm run lint              # Run ESLint
npm run format            # Run Prettier
npm run type-check        # TypeScript check
```

---

## ⚠️ Special Considerations for AI Agents

### Audio Processing Specifics

1. **Large File Handling**
   - Audio files can be large; be mindful of memory usage
   - Consider streaming processing for long tracks
   - Test with various file sizes (small, medium, large)

2. **Model Files**
   - Pre-trained models may be large (100MB - 1GB+)
   - Models should be downloaded separately, not committed to git
   - Implement model caching to avoid re-downloading

3. **Performance Considerations**
   - Audio processing is CPU/GPU intensive
   - Optimize algorithms for speed where possible
   - Consider batch processing capabilities
   - Profile code to identify bottlenecks

4. **Format Support**
   - Support common formats: MP3, WAV, FLAC, OGG, M4A
   - Handle different sample rates (22050, 44100, 48000 Hz)
   - Handle different bit depths (16-bit, 24-bit, 32-bit float)

### Testing Guidelines

1. **Test Audio Files**
   - Use small, synthetic audio files for unit tests
   - Keep test fixtures under 1MB when possible
   - Include edge cases: silence, noise, clipping

2. **Mock External Dependencies**
   - Mock model inference for faster tests
   - Mock file I/O where appropriate
   - Use fixtures instead of real model downloads

3. **Integration Tests**
   - Test with real (but small) audio samples
   - Verify output quality metrics
   - Test error handling for corrupt files

### Code Quality Standards

1. **Error Handling**
   - Validate input files exist and are readable
   - Handle unsupported formats gracefully
   - Provide clear error messages to users
   - Log errors for debugging

2. **Documentation**
   - Document all public APIs
   - Include usage examples in docstrings
   - Update README when adding features
   - Document model requirements and sources

3. **Dependencies**
   - Pin exact versions for reproducibility
   - Document why each dependency is needed
   - Minimize dependency bloat
   - Check for security vulnerabilities regularly

### Security Considerations

1. **Input Validation**
   - Validate file paths to prevent directory traversal
   - Check file sizes to prevent resource exhaustion
   - Sanitize user input in CLI/API
   - Validate audio file headers before processing

2. **External Resources**
   - Use HTTPS for model downloads
   - Verify checksums of downloaded models
   - Don't execute arbitrary code from input files
   - Be cautious with user-provided paths

### Performance Best Practices

1. **Optimize Audio I/O**
   - Use efficient libraries (librosa, soundfile)
   - Avoid unnecessary format conversions
   - Cache processed results when appropriate

2. **Memory Management**
   - Process audio in chunks for large files
   - Release resources explicitly
   - Monitor memory usage in long-running processes

3. **Parallelization**
   - Consider parallel processing for multiple files
   - Utilize GPU acceleration when available
   - Balance CPU/GPU workload

### Git and Version Control

1. **What NOT to Commit**
   - Large model files (use Git LFS or external storage)
   - User-generated audio files
   - Temporary processing files
   - Virtual environment directories (`venv/`, `node_modules/`)
   - IDE-specific files (`.vscode/`, `.idea/`)
   - OS-specific files (`.DS_Store`, `Thumbs.db`)

2. **What TO Commit**
   - Source code
   - Tests
   - Documentation
   - Configuration files (without secrets)
   - Small test fixtures
   - Requirements/dependency files

### CI/CD Expectations

1. **Automated Testing**
   - All tests should pass before merging
   - Maintain high code coverage (aim for 80%+)
   - Run linting and type checking in CI

2. **Build Verification**
   - Verify package builds successfully
   - Check for dependency conflicts
   - Validate documentation builds

3. **Release Process**
   - Use semantic versioning (MAJOR.MINOR.PATCH)
   - Tag releases in git
   - Generate changelog automatically
   - Publish to package registry (PyPI, npm)

---

## 🎯 Quick Start Checklist for AI Agents

When working on this codebase, follow this checklist:

- [ ] Read the README.md to understand project purpose
- [ ] Review this AGENTS.md file completely
- [ ] Check for existing issues or TODO comments
- [ ] Set up development environment (dependencies, tools)
- [ ] Run existing tests to ensure environment is working
- [ ] Understand the code structure before making changes
- [ ] Write tests for new functionality
- [ ] Run linting and formatting tools
- [ ] Verify tests pass with your changes
- [ ] Update documentation if needed
- [ ] Check for security implications
- [ ] Consider performance impact
- [ ] Review your changes before committing

---

## 📚 Additional Resources

### Audio Processing References
- [librosa documentation](https://librosa.org/)
- [PyTorch Audio (torchaudio)](https://pytorch.org/audio/)
- [Demucs - Music Source Separation](https://github.com/facebookresearch/demucs)
- [Spleeter by Deezer](https://github.com/deezer/spleeter)

### Machine Learning
- [PyTorch documentation](https://pytorch.org/docs/)
- [TensorFlow documentation](https://www.tensorflow.org/api_docs)

### Best Practices
- [Python Style Guide (PEP 8)](https://pep8.org/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [Airbnb JavaScript Style Guide](https://github.com/airbnb/javascript)

---

## 🤝 Contributing

When contributing to this project:

1. **Branch Naming**: Use descriptive names like `feature/stem-export`, `fix/memory-leak`, `docs/api-reference`
2. **Pull Requests**: Provide clear descriptions of changes and why they're needed
3. **Code Review**: Be open to feedback and iterate on suggestions
4. **Testing**: Ensure all tests pass and add tests for new features
5. **Documentation**: Update relevant docs with your changes

---

## 📞 Contact and Support

For questions or issues:
- Open an issue on GitHub: https://github.com/mbianchidev/track2stem/issues
- Check existing documentation in the `docs/` directory
- Review closed issues for similar problems

---

**Last Updated**: 2026-01-31  
**Version**: 1.0.0  
**Maintained By**: track2stem contributors

---

*This AGENTS.md file is intended to be a living document. As the project evolves, update this file to reflect new conventions, structures, and practices.*
