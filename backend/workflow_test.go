package main

import (
	"bytes"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestUploadMixAndArtifactWorkflow(t *testing.T) {
	root := t.TempDir()
	t.Setenv("UPLOAD_FOLDER", filepath.Join(root, "uploads"))
	t.Setenv("OUTPUT_FOLDER", filepath.Join(root, "outputs"))
	if err := os.MkdirAll(filepath.Join(root, "uploads"), 0750); err != nil {
		t.Fatal(err)
	}
	output := filepath.Join(root, "outputs", "synthetic.wav")
	artifact := filepath.Join(root, "outputs", "drums.mid")
	if err := os.MkdirAll(filepath.Dir(output), 0750); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{output, artifact} {
		if err := os.WriteFile(path, []byte("synthetic fixture"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	forwarded := make(chan string, 1)
	processor := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/process" {
			if err := r.ParseMultipartForm(1 << 20); err != nil {
				t.Error(err)
			}
			forwarded <- r.FormValue("drum_tabs")
		} else if strings.HasPrefix(r.URL.Path, "/mix/") {
			var body struct {
				Gains map[string]float64 `json:"gains"`
			}
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Error(err)
			}
			if body.Gains["drums"] != .5 {
				t.Errorf("gain was not forwarded: %v", body.Gains)
			}
		} else {
			t.Errorf("unexpected processor request: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		if err := json.NewEncoder(w).Encode(map[string]any{
			"version": 1, "outputs": map[string]string{"drums": output},
			"stem_files": map[string]string{"drums": output},
			"artifacts":  map[string]string{"drums_midi": artifact},
			"mix_stems":  []string{"drums"}, "gains": map[string]float64{"drums": .5},
			"processing_time": "1s", "analysis": map[string]any{"bpm": 120},
		}); err != nil {
			t.Error(err)
		}
	}))
	defer processor.Close()
	t.Setenv("PROCESSOR_URL", processor.URL)
	api := httptest.NewServer(newRouter())
	defer api.Close()
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, err := writer.CreateFormFile("file", "synthetic.wav")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := part.Write([]byte("synthetic audio")); err != nil {
		t.Fatal(err)
	}
	if err := writer.WriteField("drum_tabs", "true"); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	response, err := http.Post(api.URL+"/api/upload", writer.FormDataContentType(), &body)
	if err != nil {
		t.Fatal(err)
	}
	var job Job
	if err := json.NewDecoder(response.Body).Decode(&job); err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("upload status = %d", response.StatusCode)
	}
	deadline := time.Now().Add(5 * time.Second)
	for {
		response, err = http.Get(api.URL + "/api/jobs/" + job.ID)
		if err != nil {
			t.Fatal(err)
		}
		err = json.NewDecoder(response.Body).Decode(&job)
		response.Body.Close()
		if err != nil {
			t.Fatal(err)
		}
		if job.Status == "completed" {
			break
		}
		if job.Status == "failed" || time.Now().After(deadline) {
			t.Fatalf("processing did not complete: %+v", job)
		}
		time.Sleep(10 * time.Millisecond)
	}
	if <-forwarded != "true" {
		t.Fatal("requested drum transcription was omitted")
	}
	response, err = http.Post(api.URL+"/api/jobs/"+job.ID+"/mix", "application/json", strings.NewReader(`{"gains":{"drums":0.5}}`))
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("mix status = %d", response.StatusCode)
	}
	for _, path := range []string{"/api/artifacts/" + job.ID + "/drums_midi", "/api/stems/" + job.ID + "/drums"} {
		response, err = http.Get(api.URL + path)
		if err != nil {
			t.Fatal(err)
		}
		data, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil || response.StatusCode != http.StatusOK || string(data) != "synthetic fixture" {
			t.Fatalf("download %s: %d %q %v", path, response.StatusCode, data, err)
		}
	}
}
