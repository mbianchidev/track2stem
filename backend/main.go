package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/mux"
)

type Job struct {
	ID             string            `json:"id"`
	Status         string            `json:"status"` // pending, processing, completed, failed
	FileName       string            `json:"filename"`
	CreatedAt      time.Time         `json:"created_at"`
	CompletedAt    *time.Time        `json:"completed_at,omitempty"`
	Error          string            `json:"error,omitempty"`
	OutputFiles    map[string]string `json:"output_files,omitempty"`
	StemMode       string            `json:"stem_mode,omitempty"`       // "all" or "isolate"
	IsolateStem    string            `json:"isolate_stem,omitempty"`    // which stem to isolate
	ProcessingTime string            `json:"processing_time,omitempty"` // total processing time
}

var (
	jobs      = make(map[string]*Job)
	jobsMutex = &sync.RWMutex{}
	// In-memory job storage: jobs are lost on container restart
	// For production, consider using a database or persistent storage
)

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

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	router := mux.NewRouter()

	// CORS middleware
	router.Use(corsMiddleware)

	// Routes
	router.HandleFunc("/api/health", healthHandler).Methods("GET")
	router.HandleFunc("/api/upload", uploadHandler).Methods("POST")
	router.HandleFunc("/api/jobs/{id}", getJobHandler).Methods("GET")
	router.HandleFunc("/api/jobs/{id}", deleteJobHandler).Methods("DELETE")
	router.HandleFunc("/api/jobs", listJobsHandler).Methods("GET")
	router.HandleFunc("/api/download/{id}/{stem}", downloadHandler).Methods("GET")
	router.HandleFunc("/api/processing-status/{id}", processingStatusHandler).Methods("GET")

	log.Printf("Server starting on port %s", port)
	log.Fatal(http.ListenAndServe(":"+port, router))
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")

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
	err := r.ParseMultipartForm(100 << 20) // 100 MB max
	if err != nil {
		http.Error(w, "Failed to parse form", http.StatusBadRequest)
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		http.Error(w, "Failed to get file", http.StatusBadRequest)
		return
	}
	defer file.Close()

	// Get stem options from form
	stemMode := r.FormValue("stem_mode")
	if stemMode == "" {
		stemMode = "all"
	}
	isolateStem := r.FormValue("isolate_stem")
	if isolateStem == "" {
		isolateStem = "vocals"
	}

	// Create job
	jobID := uuid.New().String()
	safeFilename := sanitizeFilename(header.Filename)
	job := &Job{
		ID:          jobID,
		Status:      "pending",
		FileName:    safeFilename,
		CreatedAt:   time.Now(),
		StemMode:    stemMode,
		IsolateStem: isolateStem,
	}

	jobsMutex.Lock()
	jobs[jobID] = job
	jobsMutex.Unlock()

	// Save file
	uploadPath := filepath.Join("/app/uploads", jobID+"_"+safeFilename)
	dst, err := os.Create(uploadPath)
	if err != nil {
		job.Status = "failed"
		job.Error = "Failed to save file"
		http.Error(w, job.Error, http.StatusInternalServerError)
		return
	}
	defer dst.Close()

	if _, err := io.Copy(dst, file); err != nil {
		job.Status = "failed"
		job.Error = "Failed to save file"
		http.Error(w, job.Error, http.StatusInternalServerError)
		return
	}

	// Start processing in background
	go processJob(jobID, uploadPath, stemMode, isolateStem)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(job)
}

func processJob(jobID, filePath, stemMode, isolateStem string) {
	jobsMutex.Lock()
	job := jobs[jobID]
	job.Status = "processing"
	jobsMutex.Unlock()

	// Call processor service
	processorURL := os.Getenv("PROCESSOR_URL")
	if processorURL == "" {
		processorURL = "http://localhost:5000"
	}

	// Open the file
	file, err := os.Open(filePath)
	if err != nil {
		updateJobError(jobID, "Failed to open file")
		return
	}
	defer file.Close()

	// Create multipart form
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)

	part, err := writer.CreateFormFile("file", filepath.Base(filePath))
	if err != nil {
		updateJobError(jobID, "Failed to create form")
		return
	}

	_, err = io.Copy(part, file)
	if err != nil {
		updateJobError(jobID, "Failed to copy file")
		return
	}

	// Add job_id and stem options
	writer.WriteField("job_id", jobID)
	writer.WriteField("stem_mode", stemMode)
	writer.WriteField("isolate_stem", isolateStem)
	writer.Close()

	// Send request
	req, err := http.NewRequest("POST", processorURL+"/process", body)
	if err != nil {
		updateJobError(jobID, "Failed to create request")
		return
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())

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
	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		updateJobError(jobID, "Failed to parse response")
		return
	}

	// Update job
	jobsMutex.Lock()
	job.Status = "completed"
	now := time.Now()
	job.CompletedAt = &now

	// Extract processing time
	if processingTime, ok := result["processing_time"].(string); ok {
		job.ProcessingTime = processingTime
	}

	// Extract output files
	if outputs, ok := result["outputs"].(map[string]interface{}); ok {
		job.OutputFiles = make(map[string]string)
		for stem, path := range outputs {
			if pathStr, ok := path.(string); ok {
				job.OutputFiles[stem] = pathStr
			}
		}
	}
	jobsMutex.Unlock()
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

	jobsMutex.RLock()
	job, exists := jobs[jobID]
	jobsMutex.RUnlock()

	if !exists {
		http.Error(w, "Job not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(job)
}

func listJobsHandler(w http.ResponseWriter, r *http.Request) {
	jobsMutex.RLock()
	jobList := make([]*Job, 0, len(jobs))
	for _, job := range jobs {
		jobList = append(jobList, job)
	}
	jobsMutex.RUnlock()

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(jobList)
}

func deleteJobHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	jobID := vars["id"]

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

	// Get processing status from processor service
	processorURL := os.Getenv("PROCESSOR_URL")
	if processorURL == "" {
		processorURL = "http://processor:5000"
	}

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Get(processorURL + "/status/" + jobID)
	if err != nil {
		// Return default status if processor is not reachable
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":   "unknown",
			"progress": 0,
			"stage":    "Checking status...",
		})
		return
	}
	defer resp.Body.Close()

	// Forward the response
	w.Header().Set("Content-Type", "application/json")
	body, _ := io.ReadAll(resp.Body)
	w.Write(body)
}

func downloadHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	jobID := vars["id"]
	stem := vars["stem"]

	jobsMutex.RLock()
	job, exists := jobs[jobID]
	jobsMutex.RUnlock()

	if !exists {
		http.Error(w, "Job not found", http.StatusNotFound)
		return
	}

	if job.Status != "completed" {
		http.Error(w, "Job not completed", http.StatusBadRequest)
		return
	}

	filePath, exists := job.OutputFiles[stem]
	if !exists {
		http.Error(w, "Stem not found", http.StatusNotFound)
		return
	}

	// Check file exists
	if _, err := os.Stat(filePath); os.IsNotExist(err) {
		http.Error(w, "File not found on disk", http.StatusNotFound)
		return
	}

	// Get the actual filename from the path
	fileName := filepath.Base(filePath)
	ext := filepath.Ext(filePath)

	// Determine content type based on file extension
	contentType := "audio/mpeg" // Default to MP3
	if ext == ".wav" {
		contentType = "audio/wav"
	} else if ext == ".mp3" {
		contentType = "audio/mpeg"
	} else if ext == ".flac" {
		contentType = "audio/flac"
	}

	// Open the file
	file, err := os.Open(filePath)
	if err != nil {
		http.Error(w, "Failed to open file", http.StatusInternalServerError)
		return
	}
	defer file.Close()

	// Get file info for size
	fileInfo, err := file.Stat()
	if err != nil {
		http.Error(w, "Failed to get file info", http.StatusInternalServerError)
		return
	}

	// Set headers before writing body
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=\"%s\"", fileName))
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("Content-Length", fmt.Sprintf("%d", fileInfo.Size()))

	// Stream the file
	io.Copy(w, file)
}
