CREATE TABLE exercises (
	"index" INTEGER NOT NULL, 
	class_name VARCHAR(64) NOT NULL, 
	slug VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	exercise_id VARCHAR(36), 
	phase_supported BOOLEAN NOT NULL, 
	angle_joints VARCHAR(32), 
	down_is_decreasing BOOLEAN, 
	id INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE ("index"), 
	UNIQUE (class_name), 
	UNIQUE (slug)
);

CREATE TABLE platforms (
	id INTEGER NOT NULL, 
	name VARCHAR(16) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_platforms_name ON platforms (name);

CREATE TABLE devices (
	id INTEGER NOT NULL, 
	device_id VARCHAR(64) NOT NULL, 
	platform_id INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_device_platform_device UNIQUE (platform_id, device_id), 
	FOREIGN KEY(platform_id) REFERENCES platforms (id)
);
CREATE INDEX ix_devices_device_id ON devices (device_id);
CREATE INDEX ix_devices_platform_id ON devices (platform_id);

CREATE TABLE phase_models (
	class_name VARCHAR(64) NOT NULL, 
	version VARCHAR(32) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	bucket VARCHAR(64) NOT NULL, 
	pt_key VARCHAR(256), 
	onnx_key VARCHAR(256), 
	mlpackage_key VARCHAR(256), 
	meta_key VARCHAR(256), 
	window INTEGER NOT NULL, 
	stride INTEGER NOT NULL, 
	epochs INTEGER NOT NULL, 
	lr FLOAT NOT NULL, 
	num_files INTEGER NOT NULL, 
	metrics JSON NOT NULL, 
	mlflow_run_id VARCHAR(64), 
	error TEXT, 
	id INTEGER NOT NULL, 
	platform_id INTEGER NOT NULL, 
	exercise_fk INTEGER, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_phase_model_version UNIQUE (platform_id, class_name, version), 
	FOREIGN KEY(platform_id) REFERENCES platforms (id), 
	FOREIGN KEY(exercise_fk) REFERENCES exercises (id)
);
CREATE INDEX ix_phase_models_class_name ON phase_models (class_name);
CREATE INDEX ix_phase_models_platform_id ON phase_models (platform_id);
CREATE INDEX ix_phase_models_exercise_fk ON phase_models (exercise_fk);
CREATE INDEX ix_phase_models_status ON phase_models (status);

CREATE TABLE dataset_files (
	filename VARCHAR(128) NOT NULL, 
	class_name VARCHAR(64) NOT NULL, 
	bucket VARCHAR(64) NOT NULL, 
	s3_key VARCHAR(256) NOT NULL, 
	uploaded BOOLEAN NOT NULL, 
	phase_labeled BOOLEAN NOT NULL, 
	trained_in_version VARCHAR(32), 
	id INTEGER NOT NULL, 
	platform_id INTEGER NOT NULL, 
	device_fk INTEGER NOT NULL, 
	exercise_fk INTEGER, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_dataset_platform_filename UNIQUE (platform_id, filename), 
	FOREIGN KEY(platform_id) REFERENCES platforms (id), 
	FOREIGN KEY(device_fk) REFERENCES devices (id), 
	FOREIGN KEY(exercise_fk) REFERENCES exercises (id)
);
CREATE INDEX ix_dataset_files_class_name ON dataset_files (class_name);
CREATE INDEX ix_dataset_files_platform_id ON dataset_files (platform_id);
CREATE INDEX ix_dataset_files_device_fk ON dataset_files (device_fk);
CREATE INDEX ix_dataset_files_exercise_fk ON dataset_files (exercise_fk);

CREATE TABLE collect_files (
	filename VARCHAR(128) NOT NULL, 
	class_name VARCHAR(64) NOT NULL, 
	csv_bucket VARCHAR(64) NOT NULL, 
	csv_key VARCHAR(256) NOT NULL, 
	video_bucket VARCHAR(64) NOT NULL, 
	video_key VARCHAR(256) NOT NULL, 
	uploaded BOOLEAN NOT NULL, 
	video_start FLOAT, 
	rows INTEGER, 
	status VARCHAR(16) NOT NULL, 
	error TEXT, 
	promoted_at DATETIME, 
	id INTEGER NOT NULL, 
	platform_id INTEGER NOT NULL, 
	device_fk INTEGER NOT NULL, 
	exercise_fk INTEGER, 
	dataset_file_id INTEGER, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_collect_platform_filename UNIQUE (platform_id, filename), 
	FOREIGN KEY(platform_id) REFERENCES platforms (id), 
	FOREIGN KEY(device_fk) REFERENCES devices (id), 
	FOREIGN KEY(exercise_fk) REFERENCES exercises (id), 
	UNIQUE (dataset_file_id), 
	FOREIGN KEY(dataset_file_id) REFERENCES dataset_files (id)
);
CREATE INDEX ix_collect_files_platform_id ON collect_files (platform_id);
CREATE INDEX ix_collect_files_device_fk ON collect_files (device_fk);
CREATE INDEX ix_collect_files_status ON collect_files (status);
CREATE INDEX ix_collect_files_class_name ON collect_files (class_name);
CREATE INDEX ix_collect_files_exercise_fk ON collect_files (exercise_fk);

CREATE TABLE phase_model_files (
	phase_model_id INTEGER NOT NULL, 
	dataset_file_id INTEGER NOT NULL, 
	PRIMARY KEY (phase_model_id, dataset_file_id), 
	FOREIGN KEY(phase_model_id) REFERENCES phase_models (id), 
	FOREIGN KEY(dataset_file_id) REFERENCES dataset_files (id)
);

CREATE TABLE phase_labels (
	data_bucket VARCHAR(64) NOT NULL, 
	data_key VARCHAR(256) NOT NULL, 
	video_bucket VARCHAR(64) NOT NULL, 
	video_key VARCHAR(256) NOT NULL, 
	pose_key VARCHAR(256) NOT NULL, 
	phase_summary JSON NOT NULL, 
	labeled_at DATETIME NOT NULL, 
	id INTEGER NOT NULL, 
	collect_file_id INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (collect_file_id), 
	FOREIGN KEY(collect_file_id) REFERENCES collect_files (id)
);

