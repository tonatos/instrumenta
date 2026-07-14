package ratings

import "testing"
const sampleBondRow = `<tr class="simple-row">
<td>1</td>
<td><a href="/q/bonds/RU000A10CAQ0/">АЛЬФАДОНБ1</a></td>
<td></td><td>4.0</td><td>88.5%</td><td>51.2%</td><td>54.6%</td><td>CC</td>
</tr>
<tr class="simple-row">
<td>2</td>
<td><a href="/q/bonds/RU000A108CE5/">ЮДПАвтО Б1</a></td>
<td></td><td>2.7</td><td>240.8%</td><td>18.3%</td><td>106.0%</td><td>BB+</td>
</tr>`

func TestParseBondRows(t *testing.T) {
	got := parseBondRows(sampleBondRow)
	if got["RU000A10CAQ0"] != "ruCC" {
		t.Fatalf("RU000A10CAQ0 rating = %q, want ruCC", got["RU000A10CAQ0"])
	}
	if got["RU000A108CE5"] != "ruBB+" {
		t.Fatalf("RU000A108CE5 rating = %q, want ruBB+", got["RU000A108CE5"])
	}
}
