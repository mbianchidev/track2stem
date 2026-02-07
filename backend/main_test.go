package main

import (
	"testing"
)

func TestIsValidJobID(t *testing.T) {
	validIDs := []string{
		"abc123",
		"550e8400-e29b-41d4-a716-446655440000",
		"job-123-abc",
		"A1B2C3",
	}
	for _, id := range validIDs {
		if !isValidJobID(id) {
			t.Errorf("expected valid job ID, got invalid: %s", id)
		}
	}

	invalidIDs := []string{
		"",
		"-leading-hyphen",
		"../../etc/passwd",
		"abc/def",
		"abc;rm -rf /",
		"abc|cat /etc/passwd",
		"hello world",
		"abc\ndef",
	}
	for _, id := range invalidIDs {
		if isValidJobID(id) {
			t.Errorf("expected invalid job ID, got valid: %s", id)
		}
	}
}

func TestSanitizeFilename(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"normal.mp3", "normal.mp3"},
		{"with spaces.mp3", "with_spaces.mp3"},
		{"../../etc/passwd", "passwd"},
		{"file;rm -rf.mp3", "file_rm_-rf.mp3"},
		{"path/to/file.wav", "file.wav"},
	}
	for _, tc := range tests {
		got := sanitizeFilename(tc.input)
		if got != tc.expected {
			t.Errorf("sanitizeFilename(%q) = %q, want %q", tc.input, got, tc.expected)
		}
	}
}

func TestSafeOutputPath(t *testing.T) {
	validPaths := []string{
		"/app/outputs/job123/vocals.mp3",
		"/app/outputs/abc-def/stem.wav",
	}
	for _, p := range validPaths {
		if !safeOutputPath(p) {
			t.Errorf("expected safe path, got unsafe: %s", p)
		}
	}

	unsafePaths := []string{
		"/etc/passwd",
		"/app/uploads/secret.mp3",
		"../../etc/shadow",
		"/app/outputs/../uploads/file.mp3",
	}
	for _, p := range unsafePaths {
		if safeOutputPath(p) {
			t.Errorf("expected unsafe path, got safe: %s", p)
		}
	}
}

func TestAllowlistMaps(t *testing.T) {
	// Verify that allowlists have expected entries
	if !allowedOutputFormats["mp3"] || !allowedOutputFormats["wav"] || !allowedOutputFormats["flac"] {
		t.Error("missing expected output format in allowlist")
	}
	if !allowedStemModes["all"] || !allowedStemModes["isolate"] {
		t.Error("missing expected stem mode in allowlist")
	}
	if !allowedModels["htdemucs"] || !allowedModels["htdemucs_6s"] || !allowedModels["mdx"] {
		t.Error("missing expected model in allowlist")
	}
	if !allowedClipModes["rescale"] || !allowedClipModes["clamp"] {
		t.Error("missing expected clip mode in allowlist")
	}

	// Verify invalid values are rejected
	if allowedOutputFormats["exe"] {
		t.Error("unexpected format 'exe' in allowlist")
	}
	if allowedModels["evil_model; rm -rf /"] {
		t.Error("unexpected model with injection in allowlist")
	}
}
