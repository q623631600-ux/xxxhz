var fs = require('fs');
var code = fs.readFileSync('./web/static/app.js', 'utf-8');

// Find the brace balance at each line
var lines = code.split('\n');
var balance = 0;
var inString = false;
var stringChar = '';
var escaped = false;

for (var l = 0; l < lines.length; l++) {
    var line = lines[l];
    var lineOpen = 0;
    var lineClose = 0;

    escaped = false;
    for (var i = 0; i < line.length; i++) {
        var ch = line[i];

        if (escaped) { escaped = false; continue; }
        if (ch === '\\') { escaped = true; continue; }
        if (inString) {
            if (ch === stringChar) inString = false;
            continue;
        }
        if (ch === "'" || ch === '"' || ch === '`') {
            inString = true; stringChar = ch;
            continue;
        }
        if (ch === '{') { lineOpen++; balance++; }
        if (ch === '}') { lineClose++; balance--; }
    }

    if (lineOpen !== lineClose || balance > 5) {
        console.log('Line ' + (l+1) + ': open=' + lineOpen + ' close=' + lineClose + ' bal=' + balance + ' ' + line.trim().substring(0, 80));
    }
}

console.log('\nFinal balance:', balance);
