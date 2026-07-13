package main

import (
	"fmt"

	"github.com/booyaka101/porter"
)

func buildUpdateTasks(inv Inventory) []porter.Task {
	script := fmt.Sprintf("%s/deploy/scripts/remote-update.sh", inv.AppDir)
	cmd := fmt.Sprintf(
		"APP_DIR=%s IMAGE_TAG=%s GIT_BRANCH=%s GHCR_USERNAME=%s GHCR_TOKEN=%s bash %s",
		shellQuote(inv.AppDir),
		shellQuote(inv.ImageTag),
		shellQuote(inv.GitBranch),
		shellQuote(inv.GHCRUsername),
		shellQuote(inv.GHCRToken),
		shellQuote(script),
	)

	return porter.Tasks(
		porter.Run(cmd).Name("Update Bond Monitor on VPS").Sudo(),
	)
}
