-- MySQL schema for Amazon RDS (generated from app/db.py; the app also creates these tables itself).
CREATE DATABASE IF NOT EXISTS resumedb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE resumedb;

CREATE TABLE candidates (
	id VARCHAR(16) NOT NULL, 
	label VARCHAR(32) NOT NULL, 
	objective TEXT, 
	skills JSON, 
	degrees JSON, 
	majors JSON, 
	institutions JSON, 
	positions JSON, 
	companies JSON, 
	languages JSON, 
	certifications JSON, 
	years_experience FLOAT NOT NULL, 
	text TEXT NOT NULL, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE jobs (
	id VARCHAR(16) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	description TEXT, 
	education TEXT, 
	experience VARCHAR(100), 
	min_years FLOAT, 
	max_years FLOAT, 
	age VARCHAR(100), 
	skills JSON, 
	text TEXT NOT NULL, 
	is_custom BOOL NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE labels (
	candidate_id VARCHAR(16) NOT NULL, 
	job_id VARCHAR(16) NOT NULL, 
	matched_score FLOAT NOT NULL, 
	PRIMARY KEY (candidate_id, job_id), 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id), 
	FOREIGN KEY(job_id) REFERENCES jobs (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE ranking_runs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	job_id VARCHAR(16) NOT NULL, 
	job_title VARCHAR(255) NOT NULL, 
	created_at DATETIME NOT NULL, 
	total_candidates INTEGER NOT NULL, 
	top_k INTEGER NOT NULL, 
	embedder VARCHAR(32) NOT NULL, 
	s3_key VARCHAR(255), 
	notified BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES jobs (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE ranking_results (
	run_id INTEGER NOT NULL, 
	`rank` INTEGER NOT NULL, 
	candidate_id VARCHAR(16) NOT NULL, 
	final FLOAT NOT NULL, 
	semantic FLOAT NOT NULL, 
	skills FLOAT, 
	experience FLOAT, 
	matched_skills JSON, 
	missing_skills JSON, 
	PRIMARY KEY (run_id, `rank`), 
	FOREIGN KEY(run_id) REFERENCES ranking_runs (id), 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Useful queries for the demo / viva
-- Top 30 of the latest ranking:
-- SELECT r.`rank`, c.label, ROUND(r.final*100,1) AS score_pct FROM ranking_results r
--   JOIN candidates c ON c.id = r.candidate_id
--   WHERE r.run_id = (SELECT MAX(id) FROM ranking_runs) ORDER BY r.`rank`;
