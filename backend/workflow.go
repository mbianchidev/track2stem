package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"mime"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/mux"
)

var extraOptionNames = []string{"workers", "analysis", "click_track", "lyrics", "guitar_tabs", "bass_tabs", "drum_tabs", "split_vocals"}
var mixingJobs = make(map[string]bool)

type ProcessorResult struct {
	Version        int                `json:"version"`
	Outputs        map[string]string  `json:"outputs"`
	StemFiles      map[string]string  `json:"stem_files"`
	Artifacts      map[string]string  `json:"artifacts"`
	MixStems       []string           `json:"mix_stems"`
	Gains          map[string]float64 `json:"gains"`
	Analysis       json.RawMessage    `json:"analysis"`
	Lyrics         json.RawMessage    `json:"lyrics"`
	ProcessingTime string             `json:"processing_time"`
}

func streamUpload(path string, fields map[string]string) (*io.PipeReader, string) {
	reader, pipe := io.Pipe()
	writer := multipart.NewWriter(pipe)
	contentType := writer.FormDataContentType()
	go func() {
		err := func() error {
			file, err := os.Open(path)
			if err != nil {
				return err
			}
			defer file.Close()
			part, err := writer.CreateFormFile("file", filepath.Base(path))
			if err != nil {
				return err
			}
			if _, err := io.Copy(part, file); err != nil {
				return err
			}
			for key, value := range fields {
				if err := writer.WriteField(key, value); err != nil {
					return err
				}
			}
			return writer.Close()
		}()
		if err != nil {
			log.Printf("Cannot stream audio to processor: %v", err)
		}
		if err := pipe.CloseWithError(err); err != nil {
			log.Printf("Cannot finish processor upload stream: %v", err)
		}
	}()
	return reader, contentType
}

func uploadFolder() string {
	if value := os.Getenv("UPLOAD_FOLDER"); value != "" {
		return value
	}
	return "/app/uploads"
}

func outputFolder() string {
	if value := os.Getenv("OUTPUT_FOLDER"); value != "" {
		return value
	}
	return "/app/outputs"
}

func processorBase() string {
	if value := os.Getenv("PROCESSOR_URL"); value != "" {
		return strings.TrimRight(value, "/")
	}
	return "http://processor:5000"
}

func validateExtraOptions(options map[string]string, model string) error {
	for name, value := range options {
		if name == "workers" {
			workers, err := strconv.Atoi(value)
			if err != nil || workers < 1 || workers > 4 {
				return errors.New("workers must be an integer from 1 to 4")
			}
		} else if value != "true" && value != "false" && value != "1" && value != "0" {
			return fmt.Errorf("%s must be true or false", name)
		}
	}
	if (options["guitar_tabs"] == "true" || options["guitar_tabs"] == "1") && model != "htdemucs_6s" {
		return errors.New("guitar transcription requires the six-stem model")
	}
	return nil
}

func completeJob(jobID string, result ProcessorResult) {
	if result.Version != 1 || len(result.Outputs) == 0 {
		updateJobError(jobID, "Processor returned an incompatible or empty result")
		return
	}
	jobsMutex.Lock()
	defer jobsMutex.Unlock()
	job, exists := jobs[jobID]
	if !exists {
		return
	}
	job.Status = "completed"
	if job.CompletedAt == nil {
		now := time.Now()
		job.CompletedAt = &now
	}
	job.OutputFiles = result.Outputs
	job.StemFiles = result.StemFiles
	job.Artifacts = result.Artifacts
	job.MixStems = result.MixStems
	job.Gains = result.Gains
	job.Analysis = result.Analysis
	job.Lyrics = result.Lyrics
	job.ProcessingTime = result.ProcessingTime
}

func processorJSON(path string, value any) (ProcessorResult, int, error) {
	var result ProcessorResult
	body, err := json.Marshal(value)
	if err != nil {
		return result, http.StatusBadRequest, err
	}
	client := &http.Client{Timeout: 30 * time.Minute}
	response, err := client.Post(processorBase()+path, "application/json", bytes.NewReader(body))
	if err != nil {
		return result, http.StatusBadGateway, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		data, err := io.ReadAll(io.LimitReader(response.Body, 16000))
		if err != nil {
			return result, http.StatusBadGateway, err
		}
		var failure struct {
			Error string `json:"error"`
		}
		if err := json.Unmarshal(data, &failure); err != nil || failure.Error == "" {
			failure.Error = "The local processor rejected the request"
		}
		return result, response.StatusCode, errors.New(failure.Error)
	}
	if err := json.NewDecoder(io.LimitReader(response.Body, 8<<20)).Decode(&result); err != nil {
		return result, http.StatusBadGateway, fmt.Errorf("invalid processor response: %w", err)
	}
	return result, http.StatusOK, nil
}

func mixHandler(w http.ResponseWriter, r *http.Request) {
	jobID := mux.Vars(r)["id"]
	if !isValidJobID(jobID) {
		http.Error(w, "Invalid job ID", http.StatusBadRequest)
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 16<<10)
	var request struct {
		Gains map[string]float64 `json:"gains"`
	}
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil || request.Gains == nil {
		http.Error(w, "Provide per-instrument gains as a JSON object", http.StatusBadRequest)
		return
	}
	jobsMutex.Lock()
	job, exists := jobs[jobID]
	if !exists || job.Status != "completed" || mixingJobs[jobID] {
		jobsMutex.Unlock()
		http.Error(w, "Job is missing, incomplete, or already exporting a mix", http.StatusConflict)
		return
	}
	mixingJobs[jobID] = true
	jobsMutex.Unlock()
	defer func() {
		jobsMutex.Lock()
		delete(mixingJobs, jobID)
		jobsMutex.Unlock()
	}()
	result, status, err := processorJSON("/mix/"+jobID, request)
	if err != nil {
		log.Printf("Mix failed for %s: %v", jobID, err)
		http.Error(w, err.Error(), status)
		return
	}
	completeJob(jobID, result)
	getJobHandler(w, r)
}

func artifactHandler(w http.ResponseWriter, r *http.Request) {
	assetHandler(w, r, false)
}

func stemHandler(w http.ResponseWriter, r *http.Request) {
	assetHandler(w, r, true)
}

func assetHandler(w http.ResponseWriter, r *http.Request, preview bool) {
	vars := mux.Vars(r)
	if !isValidJobID(vars["id"]) {
		http.Error(w, "Invalid job ID", http.StatusBadRequest)
		return
	}
	jobsMutex.RLock()
	job, exists := jobs[vars["id"]]
	path := ""
	if exists && job.Status == "completed" {
		if preview {
			path = job.StemFiles[vars["asset"]]
		} else {
			path = job.Artifacts[vars["asset"]]
		}
	}
	jobsMutex.RUnlock()
	if path == "" {
		http.Error(w, "Completed asset not found", http.StatusNotFound)
		return
	}
	serveOutput(w, r, path)
}

func serveOutput(w http.ResponseWriter, r *http.Request, path string) {
	if !safeOutputPath(path) {
		http.Error(w, "Invalid output path", http.StatusBadRequest)
		return
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		log.Printf("Cannot resolve output: %v", err)
		http.Error(w, "Output file is missing or unreadable", http.StatusNotFound)
		return
	}
	if !safeOutputPath(resolved) {
		http.Error(w, "Output path escapes storage", http.StatusBadRequest)
		return
	}
	file, err := os.Open(resolved)
	if err != nil {
		log.Printf("Cannot open output: %v", err)
		http.Error(w, "Cannot open output file", http.StatusInternalServerError)
		return
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() {
		log.Printf("Cannot read output metadata: %v", err)
		http.Error(w, "Cannot read output file", http.StatusInternalServerError)
		return
	}
	contentType := map[string]string{
		".wav": "audio/wav", ".flac": "audio/flac", ".mp3": "audio/mpeg",
		".mid": "audio/midi", ".musicxml": "application/vnd.recordare.musicxml+xml",
		".json": "application/json", ".csv": "text/csv; charset=utf-8",
		".txt": "text/plain; charset=utf-8", ".srt": "application/x-subrip",
	}[strings.ToLower(filepath.Ext(path))]
	if contentType == "" {
		contentType = "application/octet-stream"
	}
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Content-Disposition", mime.FormatMediaType("attachment", map[string]string{"filename": filepath.Base(path)}))
	http.ServeContent(w, r, filepath.Base(path), info.ModTime(), file)
}

func canonicalYouTubeURL(value string) (string, error) {
	parsed, err := url.Parse(value)
	if err != nil || parsed.Scheme != "https" || parsed.User != nil || parsed.Port() != "" {
		return "", errors.New("use an HTTPS YouTube video URL")
	}
	video := ""
	switch strings.ToLower(parsed.Hostname()) {
	case "youtu.be":
		video = strings.TrimPrefix(parsed.Path, "/")
	case "youtube.com", "www.youtube.com", "m.youtube.com":
		if parsed.Path == "/watch" {
			video = parsed.Query().Get("v")
		} else if strings.HasPrefix(parsed.Path, "/shorts/") {
			video = strings.TrimPrefix(parsed.Path, "/shorts/")
		}
	}
	if !regexp.MustCompile(`^[A-Za-z0-9_-]{11}$`).MatchString(video) {
		return "", errors.New("provide a single YouTube video, not a playlist or another website")
	}
	return "https://www.youtube.com/watch?v=" + video, nil
}

func importHandler(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 16<<10)
	var request struct {
		URL      string            `json:"url"`
		Settings map[string]string `json:"settings"`
	}
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil {
		http.Error(w, "Provide a YouTube URL and settings as JSON", http.StatusBadRequest)
		return
	}
	source, err := canonicalYouTubeURL(request.URL)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	options := map[string]string{"model": "htdemucs_6s", "stem_mode": "all", "isolate_stem": "vocals",
		"output_format": "mp3", "shifts": "0", "clip_mode": "rescale"}
	for key, value := range request.Settings {
		options[key] = value
	}
	if !allowedModels[options["model"]] || !allowedOutputFormats[options["output_format"]] ||
		!allowedStemModes[options["stem_mode"]] || !allowedStems[options["isolate_stem"]] || !allowedClipModes[options["clip_mode"]] {
		http.Error(w, "Invalid separation settings", http.StatusBadRequest)
		return
	}
	extras := map[string]string{}
	for _, name := range extraOptionNames {
		if value := options[name]; value != "" {
			extras[name] = value
		}
	}
	if err := validateExtraOptions(extras, options["model"]); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	job := &Job{ID: uuid.NewString(), Status: "pending", FileName: "YouTube audio", CreatedAt: time.Now(),
		SourceURL: source, Options: options, Model: options["model"], StemMode: options["stem_mode"],
		IsolateStem: options["isolate_stem"], OutputFormat: options["output_format"]}
	jobsMutex.Lock()
	jobs[job.ID] = job
	jobsMutex.Unlock()
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(job); err != nil {
		log.Printf("Cannot return import job: %v", err)
	}
	go func() {
		jobsMutex.Lock()
		if _, exists := jobs[job.ID]; !exists {
			jobsMutex.Unlock()
			return
		}
		job.Status = "processing"
		jobsMutex.Unlock()
		result, _, err := processorJSON("/import", map[string]any{"job_id": job.ID, "url": source, "settings": options})
		if err != nil {
			updateJobError(job.ID, err.Error())
			return
		}
		completeJob(job.ID, result)
	}()
}
