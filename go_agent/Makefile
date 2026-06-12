VERSION ?= 0.2.0
LDFLAGS := -s -w -X github.com/complete3tech/scc-agent/internal/version.Version=$(VERSION)
PKG := ./cmd/scc-agent
CMD_DIR := cmd/scc-agent
GOVERSIONINFO := github.com/josephspurrier/goversioninfo/cmd/goversioninfo@latest

.PHONY: build windows test tidy lint clean

build:
	go build -ldflags "$(LDFLAGS)" -o dist/scc-agent $(PKG)

# Single Windows binary: installer + settings GUI + service in one exe.
# Generates a .syso embedding manifest.xml (UAC requireAdministrator + common
# controls) so the GUI elevates; builds as a GUI-subsystem app so double-click
# shows no console. Drop $(CMD_DIR)/icon.ico to brand the exe + shortcuts.
windows:
	go run $(GOVERSIONINFO) -64 \
		-manifest $(CMD_DIR)/manifest.xml \
		-o $(CMD_DIR)/resource_windows_amd64.syso \
		$(if $(wildcard $(CMD_DIR)/icon.ico),-icon $(CMD_DIR)/icon.ico,) \
		$(CMD_DIR)/versioninfo.json
	GOOS=windows GOARCH=amd64 go build -ldflags "$(LDFLAGS) -H windowsgui" -o dist/scc-agent.exe $(PKG)

test:
	go test ./...

tidy:
	go mod tidy

lint:
	go vet ./...

clean:
	rm -rf dist $(CMD_DIR)/resource_windows_amd64.syso
