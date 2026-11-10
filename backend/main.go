package main

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/mux"
)

type Job struct {
	ID             string             `json:"id"`
	Status         string             `json:"status"` // pending, processing, completed, failed
	FileName       string             `json:"filename"`
	CreatedAt      time.Time          `json:"created_at"`
	CompletedAt    *time.Time         `json:"completed_at,omitempty"`
	Error          string             `json:"error,omitempty"`
	OutputFiles    map[string]string  `json:"output_files,omitempty"`
	StemMode       string             `json:"stem_mode,omitempty"`       // "all" or "isolate"
	IsolateStem    string             `json:"isolate_stem,omitempty"`    // which stem to isolate
	ProcessingTime string             `json:"processing_time,omitempty"` // total processing time
	OutputFormat   string             `json:"output_format,omitempty"`   // mp3, wav, flac
	Model          string             `json:"model,omitempty"`           // demucs model name
	Segment        string             `json:"segment,omitempty"`         // segment size for memory management
	Overlap        string             `json:"overlap,omitempty"`         // overlap between prediction windows
	Shifts         string             `json:"shifts,omitempty"`          // shift trick for better quality
	ClipMode       string             `json:"clip_mode,omitempty"`       // rescale or clamp
	Options        map[string]string  `json:"options,omitempty"`
	Artifacts      map[string]string  `json:"artifacts,omitempty"`
	StemFiles      map[string]string  `json:"stem_files,omitempty"`
	MixStems       []string           `json:"mix_stems,omitempty"`
	Gains          map[string]float64 `json:"gains,omitempty"`
	Analysis       json.RawMessage    `json:"analysis,omitempty"`
	Lyrics         json.RawMessage    `json:"lyrics,omitempty"`
	VocalSplit     json.RawMessage    `json:"vocal_split,omitempty"`
	SourceURL      string             `json:"source_url,omitempty"`
}

var (
	jobs      = make(map[string]*Job)
	jobsMutex = &sync.RWMutex{}
	// In-memory job storage: jobs are lost on container restart
	// For production, consider using a database or persistent storage
)

// jobIDPattern validates that job IDs only contain UUID-safe characters
var jobIDPattern = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9\-]{0,254}$`)

// Allowlists for user-supplied form values (defense-in-depth; processor also validates)
var (
	allowedOutputFormats = map[string]bool{"mp3": true, "wav": true, "flac": true}
	allowedStemModes     = map[string]bool{"all": true, "isolate": true}
	allowedStems         = map[string]bool{"vocals": true, "drums": true, "bass": true, "guitar": true, "piano": true, "other": true}
	allowedModels        = map[string]bool{
		"htdemucs": true, "htdemucs_ft": true, "htdemucs_6s": true, "hdemucs_mmi": true,
		"mdx": true, "mdx_extra": true, "mdx_q": true, "mdx_extra_q": true,
	}
	allowedClipModes = map[string]bool{"rescale": true, "clamp": true}
)

// isValidJobID checks that a job ID contains only alphanumeric chars and hyphens
func isValidJobID(id string) bool {
	return jobIDPattern.MatchString(id)
}

// sanitizeFilename removes dangerous characters from filenames to prevent path traversal
func sanitizeFilename(filename string) string {
	// Remove any path separators
	filename = filepath.Base(filename)
	// Remove or replace dangerous characters
	reg := regexp.MustCompile(`[^a-zA-Z0-9._-]`)
	filename = reg.ReplaceAllString(filename, "_")
	// Limit length
	if len(filename) > 255 {
		ext := filepath.Ext(filename)
		filename = filename[:255-len(ext)] + ext
	}
	return filename
}

// safeOutputPath validates that a file path is rooted under /app/outputs
func safeOutputPath(path string) bool {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return false
	}
	base, err := filepath.Abs(outputFolder())
	if err != nil {
		return false
	}
	if resolved, err := filepath.EvalSymlinks(base); err == nil {
		base = resolved
	}
	if resolved, err := filepath.EvalSymlinks(absPath); err == nil {
		absPath = resolved
	}
	relative, err := filepath.Rel(base, absPath)
	return err == nil && relative != "." && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator))
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	if err := os.MkdirAll(uploadFolder(), 0750); err != nil {
		log.Fatal("Cannot create upload storage: ", err)
	}
	router := newRouter()

	log.Printf("Server starting on port %s", port)
	log.Fatal(http.ListenAndServe(":"+port, router))
}

func newRouter() http.Handler {
	router := mux.NewRouter()

	// Routes
	router.HandleFunc("/api/health", healthHandler).Methods("GET")
	router.HandleFunc("/api/upload", uploadHandler).Methods("POST")
	router.HandleFunc("/api/jobs/{id}", getJobHandler).Methods("GET")
	router.HandleFunc("/api/jobs/{id}", deleteJobHandler).Methods("DELETE")
	router.HandleFunc("/api/jobs", listJobsHandler).Methods("GET")
	router.HandleFunc("/api/download/{id}/{stem}", downloadHandler).Methods("GET")
	router.HandleFunc("/api/processing-status/{id}", processingStatusHandler).Methods("GET")
	router.HandleFunc("/api/jobs/{id}/mix", mixHandler).Methods("POST")
	router.HandleFunc("/api/artifacts/{id}/{asset}", artifactHandler).Methods("GET")
	router.HandleFunc("/api/stems/{id}/{asset}", stemHandler).Methods("GET")
	router.HandleFunc("/api/import", importHandler).Methods("POST")
	return corsMiddleware(router)
}

func corsMiddleware(next http.Handler) http.Handler {
	// Get allowed origins from environment variable
	// ALLOWED_ORIGINS can be a comma-separated list of allowed origins
	// Default to "*" for development if not set
	allowedOriginsEnv := os.Getenv("ALLOWED_ORIGINS")
	if allowedOriginsEnv == "" {
		allowedOriginsEnv = "*"
	}

	// Parse allowed origins once at startup for O(1) lookup
	allowAll := allowedOriginsEnv == "*"
	allowedOriginsMap := make(map[string]bool)
	if !allowAll {
		for _, origin := range strings.Split(allowedOriginsEnv, ",") {
			trimmed := strings.TrimSpace(origin)
			if trimmed != "" {
				allowedOriginsMap[trimmed] = true
			}
		}
	}

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		originAllowed := false

		// Check if the origin is allowed
		if allowAll {
			w.Header().Set("Access-Control-Allow-Origin", "*")
			originAllowed = true
		} else if origin != "" && allowedOriginsMap[origin] {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			originAllowed = true
		}

		// Only set other CORS headers if origin is allowed
		if originAllowed {
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		}

		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}

		next.ServeHTTP(w, r)
	})
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func uploadHandler(w http.ResponseWriter, r *http.Request) {
	// Parse multipart form
	r.Body = http.MaxBytesReader(w, r.Body, 101<<20)
	err := r.ParseMultipartForm(100 << 20) // 100 MB max
	if err != nil {
		http.Error(w, "Failed to parse form", http.StatusBadRequest)
		return
	}
	defer r.MultipartForm.RemoveAll()

	file, header, err := r.FormFile("file")
	if err != nil {
		http.Error(w, "Failed to get file", http.StatusBadRequest)
		return
	}
	defer file.Close()
	if header.Size > 100<<20 {
		http.Error(w, "File is too large. Maximum allowed size is 100 MiB.", http.StatusRequestEntityTooLarge)
		return
	}
	extension := strings.ToLower(filepath.Ext(header.Filename))
	if !map[string]bool{".mp3": true, ".wav": true, ".flac": true, ".ogg": true, ".m4a": true, ".aac": true}[extension] {
		http.Error(w, "Unsupported audio file type", http.StatusBadRequest)
		return
	}

	// Get stem options from form
	stemMode := r.FormValue("stem_mode")
	if stemMode == "" {
		stemMode = "all"
	}
	isolateStem := r.FormValue("isolate_stem")
	if isolateStem == "" {
		isolateStem = "vocals"
	}

	// Get advanced options from form
	outputFormat := r.FormValue("output_format")
	if outputFormat == "" {
		outputFormat = "mp3"
	}
	model := r.FormValue("model")
	if model == "" {
		model = "htdemucs_6s"
	}
	segment := r.FormValue("segment")
	overlap := r.FormValue("overlap")
	shifts := r.FormValue("shifts")
	if shifts == "" {
		shifts = "0"
	}
	clipMode := r.FormValue("clip_mode")
	if clipMode == "" {
		clipMode = "rescale"
	}

	// Validate all user-supplied options against allowlists
	if !allowedStemModes[stemMode] {
		http.Error(w, "Invalid stem_mode value", http.StatusBadRequest)
		return
	}
	if stemMode == "isolate" && !allowedStems[isolateStem] {
		http.Error(w, "Invalid isolate_stem value", http.StatusBadRequest)
		return
	}
	if !allowedOutputFormats[outputFormat] {
		http.Error(w, "Invalid output_format value", http.StatusBadRequest)
		return
	}
	if !allowedModels[model] {
		http.Error(w, "Invalid model value", http.StatusBadRequest)
		return
	}
	if !allowedClipModes[clipMode] {
		http.Error(w, "Invalid clip_mode value", http.StatusBadRequest)
		return
	}
	options := map[string]string{}
	for _, name := range extraOptionNames {
		if value := r.FormValue(name); value != "" {
			options[name] = value
		}
	}
	if err := validateExtraOptions(options, model); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	// Create job
	jobID := uuid.New().String()
	safeFilename := sanitizeFilename(header.Filename)
	job := &Job{
		ID:           jobID,
		Status:       "pending",
		FileName:     safeFilename,
		CreatedAt:    time.Now(),
		StemMode:     stemMode,
		IsolateStem:  isolateStem,
		OutputFormat: outputFormat,
		Model:        model,
		Segment:      segment,
		Overlap:      overlap,
		Shifts:       shifts,
		ClipMode:     clipMode,
		Options:      options,
	}

	jobsMutex.Lock()
	jobs[jobID] = job
	jobsMutex.Unlock()

	// Save file
	uploadPath := filepath.Join(uploadFolder(), jobID+"_"+safeFilename)
	dst, err := os.Create(uploadPath)
	if err != nil {
		updateJobError(jobID, "Failed to save file")
		log.Printf("Cannot create upload: %v", err)
		http.Error(w, "Failed to save file", http.StatusInternalServerError)
		return
	}
	if _, err := io.Copy(dst, file); err != nil {
		dst.Close()
		os.Remove(uploadPath)
		updateJobError(jobID, "Failed to save file")
		log.Printf("Cannot save upload: %v", err)
		http.Error(w, "Failed to save file", http.StatusInternalServerError)
		return
	}
	if err := dst.Close(); err != nil {
		updateJobError(jobID, "Failed to finish saving file")
		log.Printf("Cannot finish upload: %v", err)
		http.Error(w, "Failed to finish saving file", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(job)
	go processJob(jobID, uploadPath, stemMode, isolateStem, outputFormat, model, segment, overlap, shifts, clipMode)
}

func processJob(jobID, filePath, stemMode, isolateStem, outputFormat, model, segment, overlap, shifts, clipMode string) {
	defer func() {
		if err := os.Remove(filePath); err != nil && !os.IsNotExist(err) {
			log.Printf("Cannot remove owned upload for %s: %v", jobID, err)
		}
	}()
	jobsMutex.Lock()
	job, exists := jobs[jobID]
	if !exists {
		jobsMutex.Unlock()
		return
	}
	job.Status = "processing"
	options := job.Options
	jobsMutex.Unlock()

	// Call processor service
	processorURL := os.Getenv("PROCESSOR_URL")
	if processorURL == "" {
		processorURL = "http://localhost:5000"
	}

	fields := map[string]string{
		"job_id": jobID, "stem_mode": stemMode, "isolate_stem": isolateStem,
		"output_format": outputFormat, "model": model, "shifts": shifts, "clip_mode": clipMode,
	}
	if segment != "" {
		fields["segment"] = segment
	}
	if overlap != "" {
		fields["overlap"] = overlap
	}
	for name, value := range options {
		fields[name] = value
	}
	body, contentType := streamUpload(filePath, fields)
	defer body.Close()

	// Send request
	req, err := http.NewRequest("POST", processorURL+"/process", body)
	if err != nil {
		updateJobError(jobID, "Failed to create request")
		return
	}
	req.Header.Set("Content-Type", contentType)

	client := &http.Client{Timeout: 30 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		updateJobError(jobID, "Failed to process: "+err.Error())
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		updateJobError(jobID, "Processor failed: "+string(respBody))
		return
	}

	// Parse response
	var result ProcessorResult
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		updateJobError(jobID, "Failed to parse response")
		return
	}

	// Update job
	completeJob(jobID, result)
}

func updateJobError(jobID, errMsg string) {
	jobsMutex.Lock()
	defer jobsMutex.Unlock()

	if job, exists := jobs[jobID]; exists {
		job.Status = "failed"
		job.Error = errMsg
		now := time.Now()
		job.CompletedAt = &now
	}
}

func getJobHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	jobID := vars["id"]

	if !isValidJobID(jobID) {
		http.Error(w, "Invalid job ID", http.StatusBadRequest)
		return
	}

	jobsMutex.RLock()
	defer jobsMutex.RUnlock()
	job, exists := jobs[jobID]

	if !exists {
		http.Error(w, "Job not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(job)
}

func listJobsHandler(w http.ResponseWriter, r *http.Request) {
	jobsMutex.RLock()
	defer jobsMutex.RUnlock()
	jobList := make([]*Job, 0, len(jobs))
	for _, job := range jobs {
		jobList = append(jobList, job)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(jobList)
}

func deleteJobHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	jobID := vars["id"]

	if !isValidJobID(jobID) {
		http.Error(w, "Invalid job ID", http.StatusBadRequest)
		return
	}

	jobsMutex.RLock()
	job, exists := jobs[jobID]
	wasProcessing := exists && (job.Status == "pending" || job.Status == "processing")
	jobsMutex.RUnlock()

	// If job was processing, cancel it in the processor
	if wasProcessing {
		processorURL := os.Getenv("PROCESSOR_URL")
		if processorURL == "" {
			processorURL = "http://processor:5000"
		}

		// Call processor cancel endpoint
		client := &http.Client{Timeout: 10 * time.Second}
		cancelReq, err := http.NewRequest("POST", processorURL+"/cancel/"+jobID, nil)
		if err == nil {
			resp, err := client.Do(cancelReq)
			if err != nil {
				log.Printf("Failed to cancel job in processor: %v", err)
			} else {
				resp.Body.Close()
				log.Printf("Cancelled job %s in processor", jobID)
			}
		}
	}

	jobsMutex.Lock()
	job, exists = jobs[jobID]
	if exists {
		// Mark as cancelled/failed if still processing
		if job.Status == "pending" || job.Status == "processing" {
			job.Status = "failed"
			job.Error = "Cancelled by user"
			now := time.Now()
			job.CompletedAt = &now
		}
		delete(jobs, jobID)
	}
	jobsMutex.Unlock()

	if !exists {
		http.Error(w, "Job not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "deleted"})
}

func processingStatusHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	jobID := vars["id"]

	if !isValidJobID(jobID) {
		http.Error(w, "Invalid job ID", http.StatusBadRequest)
		return
	}

	// Get processing status from processor service
	processorURL := os.Getenv("PROCESSOR_URL")
	if processorURL == "" {
		processorURL = "http://processor:5000"
	}

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Get(processorURL + "/status/" + jobID)
	if err != nil {
		log.Printf("Cannot read processor progress: %v", err)
		http.Error(w, "Processor progress is unavailable", http.StatusServiceUnavailable)
		return
	}
	defer resp.Body.Close()

	// Forward the response
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	if _, err := io.Copy(w, resp.Body); err != nil {
		log.Printf("Cannot forward processor progress: %v", err)
	}
}

func downloadHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	jobID := vars["id"]
	stem := vars["stem"]

	if !isValidJobID(jobID) {
		http.Error(w, "Invalid job ID", http.StatusBadRequest)
		return
	}

	jobsMutex.RLock()
	job, exists := jobs[jobID]
	var status, filePath string
	var fileExists bool
	if exists {
		status = job.Status
		filePath, fileExists = job.OutputFiles[stem]
	}
	jobsMutex.RUnlock()

	if !exists {
		http.Error(w, "Job not found", http.StatusNotFound)
		return
	}

	if status != "completed" {
		http.Error(w, "Job not completed", http.StatusBadRequest)
		return
	}

	if !fileExists {
		http.Error(w, "Stem not found", http.StatusNotFound)
		return
	}

	serveOutput(w, r, filePath)
}
