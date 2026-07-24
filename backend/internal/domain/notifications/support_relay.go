package notifications

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

const supportHeaderPrefix = "Support tg_id="

var supportTgIDRe = regexp.MustCompile(`(?m)^Support tg_id=(\d+)\s*$`)

// FormatSupportRelayMessage builds the operator-inbox text with a parsable header.
func FormatSupportRelayMessage(tgID int64, username, planLabel, body string) string {
	meta := strings.TrimSpace(username)
	if meta != "" && !strings.HasPrefix(meta, "@") {
		meta = "@" + meta
	}
	planLabel = strings.TrimSpace(planLabel)
	if planLabel == "" {
		planLabel = "free"
	}
	line2 := planLabel
	if meta != "" {
		line2 = meta + " · " + planLabel
	}
	body = strings.TrimSpace(body)
	return fmt.Sprintf("%s%d\n%s\n---\n%s", supportHeaderPrefix, tgID, line2, body)
}

// ParseSupportTgID extracts the user telegram id from a support relay header
// (typically reply_to_message.Text in the operator group).
func ParseSupportTgID(replyToText string) (int64, bool) {
	m := supportTgIDRe.FindStringSubmatch(replyToText)
	if len(m) < 2 {
		return 0, false
	}
	id, err := strconv.ParseInt(m[1], 10, 64)
	if err != nil || id == 0 {
		return 0, false
	}
	return id, true
}

// SupportDeepLink appends ?start=support to a bot deep link (https://t.me/name).
func SupportDeepLink(deepLink string) string {
	deepLink = strings.TrimSpace(deepLink)
	if deepLink == "" {
		return ""
	}
	if strings.Contains(deepLink, "start=support") {
		return deepLink
	}
	if i := strings.IndexByte(deepLink, '?'); i >= 0 {
		base := deepLink[:i]
		q := deepLink[i+1:]
		if q == "" {
			return base + "?start=support"
		}
		return base + "?start=support&" + q
	}
	return deepLink + "?start=support"
}
