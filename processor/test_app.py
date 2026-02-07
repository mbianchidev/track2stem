"""Tests for input validation and path safety in processor/app.py"""
import os
import json
import io
import pytest

from app import (
    validate_job_id,
    safe_join,
    app,
    ALLOWED_STEMS,
    ALLOWED_OUTPUT_FORMATS,
    ALLOWED_STEM_MODES,
    ALLOWED_MODELS,
    ALLOWED_CLIP_MODES,
    ALLOWED_SHIFTS,
    ALLOWED_SEGMENTS,
    ALLOWED_OVERLAPS,
    SIX_STEM_MODELS,
)


class TestValidateJobId:
    """Test job_id validation."""

    def test_valid_uuid(self):
        assert validate_job_id('550e8400-e29b-41d4-a716-446655440000') is True

    def test_valid_alphanumeric(self):
        assert validate_job_id('abc123') is True

    def test_valid_with_hyphens(self):
        assert validate_job_id('job-123-abc') is True

    def test_empty_string(self):
        assert validate_job_id('') is False

    def test_none(self):
        assert validate_job_id(None) is False

    def test_path_traversal_dots(self):
        assert validate_job_id('../../etc') is False

    def test_path_traversal_slashes(self):
        assert validate_job_id('../passwd') is False

    def test_forward_slash(self):
        assert validate_job_id('abc/def') is False

    def test_backslash(self):
        assert validate_job_id('abc\\def') is False

    def test_spaces(self):
        assert validate_job_id('abc def') is False

    def test_semicolon_injection(self):
        assert validate_job_id('abc;rm -rf /') is False

    def test_pipe_injection(self):
        assert validate_job_id('abc|cat /etc/passwd') is False

    def test_backtick_injection(self):
        assert validate_job_id('abc`whoami`') is False

    def test_dollar_injection(self):
        assert validate_job_id('$(whoami)') is False

    def test_starts_with_hyphen(self):
        assert validate_job_id('-abc') is False


class TestSafeJoin:
    """Test path traversal prevention."""

    def test_normal_join(self):
        result = safe_join('/app/uploads', 'test.mp3')
        assert result == os.path.realpath('/app/uploads/test.mp3')

    def test_nested_join(self):
        result = safe_join('/app/outputs', 'job123', 'stem.mp3')
        assert result == os.path.realpath('/app/outputs/job123/stem.mp3')

    def test_path_traversal_raises(self):
        with pytest.raises(ValueError, match="Path traversal detected"):
            safe_join('/app/uploads', '../../etc/passwd')

    def test_path_traversal_with_dots(self):
        with pytest.raises(ValueError, match="Path traversal detected"):
            safe_join('/app/outputs', '../uploads/secret')

    def test_absolute_path_escape(self):
        with pytest.raises(ValueError, match="Path traversal detected"):
            safe_join('/app/uploads', '/etc/passwd')


class TestEndpointValidation:
    """Test that endpoints reject invalid inputs."""

    @pytest.fixture
    def client(self):
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_status_invalid_job_id(self, client):
        resp = client.get('/status/abc;rm -rf')
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data['error'] == 'Invalid job ID'

    def test_status_valid_job_id(self, client):
        resp = client.get('/status/abc-123-def')
        assert resp.status_code == 200

    def test_cancel_invalid_job_id(self, client):
        resp = client.post('/cancel/abc;rm -rf')
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data['error'] == 'Invalid job ID'

    def test_process_invalid_job_id(self, client):
        data = {
            'job_id': '../../etc/passwd',
            'output_format': 'mp3',
            'stem_mode': 'all',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Invalid job ID'

    def test_process_invalid_output_format(self, client):
        data = {
            'job_id': 'valid-job-123',
            'output_format': 'exe',
            'stem_mode': 'all',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Invalid output format'

    def test_process_invalid_stem_mode(self, client):
        data = {
            'job_id': 'valid-job-123',
            'output_format': 'mp3',
            'stem_mode': 'malicious',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Invalid stem mode'

    def test_process_invalid_isolate_stem(self, client):
        data = {
            'job_id': 'valid-job-123',
            'output_format': 'mp3',
            'stem_mode': 'isolate',
            'isolate_stem': '../../etc/passwd',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Invalid isolate stem'

    def test_process_invalid_model(self, client):
        data = {
            'job_id': 'valid-job-456',
            'output_format': 'mp3',
            'stem_mode': 'all',
            'model': 'evil_model; rm -rf /',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Invalid model'

    def test_process_invalid_clip_mode(self, client):
        data = {
            'job_id': 'valid-job-789',
            'output_format': 'wav',
            'stem_mode': 'all',
            'clip_mode': 'delete',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Invalid clip mode'

    def test_process_invalid_shifts(self, client):
        data = {
            'job_id': 'valid-job-aaa',
            'output_format': 'mp3',
            'stem_mode': 'all',
            'shifts': '99',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Invalid shifts value'

    def test_process_invalid_segment(self, client):
        data = {
            'job_id': 'valid-job-bbb',
            'output_format': 'mp3',
            'stem_mode': 'all',
            'segment': '999',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Invalid segment value'

    def test_process_invalid_overlap(self, client):
        data = {
            'job_id': 'valid-job-ccc',
            'output_format': 'flac',
            'stem_mode': 'all',
            'overlap': '0.99',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Invalid overlap value'

    def test_process_flac_format_accepted(self, client):
        """Verify 'flac' is accepted by the output_format validator."""
        assert 'flac' in ALLOWED_OUTPUT_FORMATS

    def test_process_valid_model_accepted(self, client):
        """All expected model names should be in the allowlist."""
        expected = {'htdemucs', 'htdemucs_ft', 'htdemucs_6s',
                    'hdemucs_mmi', 'mdx', 'mdx_extra',
                    'mdx_q', 'mdx_extra_q'}
        assert expected.issubset(ALLOWED_MODELS)

    def test_process_non_numeric_shifts(self, client):
        data = {
            'job_id': 'valid-job-nn1',
            'output_format': 'mp3',
            'stem_mode': 'all',
            'shifts': 'abc',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Invalid shifts value'

    def test_process_non_numeric_segment(self, client):
        data = {
            'job_id': 'valid-job-nn2',
            'output_format': 'mp3',
            'stem_mode': 'all',
            'segment': 'xyz',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Invalid segment value'

    def test_process_non_numeric_overlap(self, client):
        data = {
            'job_id': 'valid-job-nn3',
            'output_format': 'mp3',
            'stem_mode': 'all',
            'overlap': 'not-a-number',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Invalid overlap value'

    def test_process_incompatible_isolate_stem_for_4stem_model(self, client):
        """4-stem models should reject guitar/piano in isolate mode."""
        data = {
            'job_id': 'valid-job-compat',
            'output_format': 'mp3',
            'stem_mode': 'isolate',
            'isolate_stem': 'guitar',
            'model': 'htdemucs',
        }
        resp = client.post(
            '/process',
            data={**data, 'file': (io.BytesIO(b'fake audio'), 'test.mp3')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body['error'] == 'Incompatible isolate_stem for selected model'


class TestModelStemMapping:
    """Verify stem counts per model family."""

    def test_six_stem_model_set(self):
        assert 'htdemucs_6s' in SIX_STEM_MODELS

    def test_four_stem_models_not_in_six(self):
        four_stem = {'htdemucs', 'htdemucs_ft', 'hdemucs_mmi',
                     'mdx', 'mdx_extra', 'mdx_q', 'mdx_extra_q'}
        for m in four_stem:
            assert m not in SIX_STEM_MODELS
