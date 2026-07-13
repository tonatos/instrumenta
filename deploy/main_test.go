package main

import "testing"

func TestParseCLI(t *testing.T) {
	command, inventory, key, dryRun, err := parseCLI([]string{"bootstrap", "-dry-run"})
	if err != nil {
		t.Fatalf("parseCLI: %v", err)
	}
	if command != "bootstrap" || !dryRun || inventory != defaultInventoryPath || key != "" {
		t.Fatalf("unexpected parse result: command=%q dryRun=%v inventory=%q key=%q", command, dryRun, inventory, key)
	}

	command, inventory, key, dryRun, err = parseCLI([]string{
		"update", "-inventory", "custom.yaml", "-key", "~/.ssh/custom",
	})
	if err != nil {
		t.Fatalf("parseCLI with flags: %v", err)
	}
	if command != "update" || dryRun || inventory != "custom.yaml" || key != "~/.ssh/custom" {
		t.Fatalf("unexpected parse result: command=%q dryRun=%v inventory=%q key=%q", command, dryRun, inventory, key)
	}
}

func TestParseCLIRejectsUnknownCommand(t *testing.T) {
	_, _, _, _, err := parseCLI([]string{"sync"})
	if err == nil {
		t.Fatal("expected error for unknown command")
	}
}
