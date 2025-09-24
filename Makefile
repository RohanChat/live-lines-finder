# --- Configuration ---
IMAGE_NAME := betting-assistant
IMAGE_TAG := latest

# --- Targets ---
.PHONY: all build run-web run-imessage run-mock stop clean requirements

all: build

requirements:
	@echo "--- Generating requirements.txt ---"
	@pip freeze > requirements.txt

build: requirements
	@echo "--- Building Docker image: $(IMAGE_NAME):$(IMAGE_TAG) ---"
	@docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

run-web:
	@echo "--- Running Web App Container ---"
	@docker run --rm -it --name $(IMAGE_NAME)-web \
		--env-file .env \
		-p 8000:8000 \
		$(IMAGE_NAME):$(IMAGE_TAG)

run-imessage:
	@echo "--- Running iMessage Bot Container ---"
	@docker run --rm -it --name $(IMAGE_NAME)-imessage \
		--env-file .env \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		python3 run_chatbot.py --platform imessage --feeds theoddsapi

run-mock:
	@echo "--- Running Mock CLI Container ---"
	@docker run --rm -it --name $(IMAGE_NAME)-mock \
		--env-file .env \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		python3 run_chatbot.py --platform mock --feeds theoddsapi

stop:
	@echo "--- Stopping all running containers for this project ---"
	@docker stop $(shell docker ps -q --filter "name=$(IMAGE_NAME)-*") || true

clean: stop
	@echo "--- Removing all stopped containers for this project ---"
	@docker rm $(shell docker ps -a -q --filter "name=$(IMAGE_NAME)-*") || true
