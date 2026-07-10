var fs = require('fs');
var code = fs.readFileSync('D:/讲书升级Agent/web/static/app.js', 'utf-8');
var line = code.split('\n')[101];

// Break line into pieces at each closing single-quote boundary
// Pattern: string + var + string + var + ...
// Split by: ' + something + '
var ctx = { borderColor: 'red', bookName: 'test', kpId: 1, encodeURIComponent: function(x){return x;} };
var result = '';
var remaining = line.trim();

// Check by actually trying to eval incrementally
// Find all positions of ' + and + '
var positions = [];
for (var i = 0; i < line.length; i++) {
    if (line[i] === "'" && i+3 < line.length && line[i+1] === ' ' && line[i+2] === '+' && line[i+3] === ' ') {
        if (i > 0 && i > (positions[positions.length-1] || 0) + 5) {
            positions.push(i);
        }
    }
}
console.log('Found', positions.length, 'string-split positions');

// Try parsing incrementally
var build = '';
var lastPos = -1;
var marker = 0;
while (marker < line.length) {
    var nextPos = -1;
    for (var i = 0; i < positions.length; i++) {
        if (positions[i] > marker) {
            nextPos = positions[i];
            break;
        }
    }
    if (nextPos < 0) {
        build = line.substring(0, line.length);
        marker = line.length;
    } else {
        // Include the quote and the ' + ' prefix
        var nextBoundary = nextPos;
        // Find the corresponding closing quote from the first '
        build = line.substring(0, nextPos);
        marker = nextPos;
    }

    try {
        // Replace variable names with values
        var testCode = build.replace(/borderColor/g, '"red"').replace(/bookName/g, '"test"').replace(/kpId/g, '1').replace(/encodeURIComponent\(/g, '(function(x){return x})(');
        // Check if it parses
        eval('0;' + testCode);
        // It parsed, continue
    } catch(e) {
        console.log('Failed at position', marker);
        console.log('Context:', line.substring(Math.max(0, marker-20), marker+20));
        console.log('Error:', e.message.substring(0, 80));
        break;
    }
}
