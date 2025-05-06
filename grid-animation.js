// grid-animation.js
(function($) {
    let nodes = [];
    let waveTime = 0;
  
    $(window).on('elementor/frontend/init', function () {
      elementorFrontend.hooks.addAction('frontend/element_ready/global', function($scope) {
        const canvas = $scope.find('#fleetGridCanvas')[0];
        if (!canvas) return;
  
        const ctx = canvas.getContext('2d');
        const settings = window.fleetGridSettings || {};
  
        const brandColor = settings.brandColor || '#CC6802';
        const nodeSize = parseFloat(settings.nodeSize || 2);
        const spacing = parseInt(settings.gridSpacing || 50);
        const glowRadius = parseFloat(settings.glowRadius || 5);
        const glowOpacity = parseFloat(settings.glowOpacity || 0.1);
        const waveSpeed = parseFloat(settings.waveSpeed || 1.5);
  
        let width = window.innerWidth;
        let height = window.innerHeight;
        canvas.width = width;
        canvas.height = height;
  
        function generateGrid() {
          nodes = [];
          const top = height * 0.65;
          const bottom = height;
          const leftBound = 0;
          const rightBound = width;
  
          for (let x = 0; x <= width; x += spacing) {
            if (x < width * 0.25 || x > width * 0.75) {
              for (let y = top; y <= bottom; y += spacing) {
                nodes.push({
                  x,
                  y,
                  color: Math.random() < 0.5 ? '#FFFFFF' : brandColor
                });
              }
            }
          }
        }
  
        function drawGrid() {
          ctx.clearRect(0, 0, width, height);
  
          // vertical lines (left + right only)
          for (let x = 0; x <= width; x += spacing) {
            if (x < width * 0.25 || x > width * 0.75) {
              ctx.beginPath();
              ctx.moveTo(x, height * 0.65);
              ctx.lineTo(x, height);
              ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
              ctx.stroke();
            }
          }
  
          // horizontal lines (bottom 35% only)
          for (let y = height * 0.65; y <= height; y += spacing) {
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(width, y);
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
            ctx.stroke();
          }
  
          // wave effect
          const waveOrigin = height;
          waveTime += 0.03 * waveSpeed;
  
          nodes.forEach(node => {
            const dist = Math.abs(node.y - waveOrigin - Math.sin(waveTime + node.x * 0.01) * 30);
            const glow = Math.max(0, 1 - dist / 50);
  
            // glow
            if (glow > 0) {
              ctx.beginPath();
              ctx.arc(node.x, node.y, glowRadius, 0, Math.PI * 2);
              ctx.fillStyle = hexToRGBA(node.color, glow * glowOpacity);
              ctx.fill();
            }
  
            // node
            ctx.beginPath();
            ctx.arc(node.x, node.y, nodeSize, 0, Math.PI * 2);
            ctx.fillStyle = node.color;
            ctx.fill();
          });
  
          requestAnimationFrame(drawGrid);
        }
  
        function hexToRGBA(hex, alpha) {
          const r = parseInt(hex.substring(1, 3), 16);
          const g = parseInt(hex.substring(3, 5), 16);
          const b = parseInt(hex.substring(5, 7), 16);
          return `rgba(${r},${g},${b},${alpha})`;
        }
  
        generateGrid();
        drawGrid();
  
        $(window).on('resize', () => {
          width = window.innerWidth;
          height = window.innerHeight;
          canvas.width = width;
          canvas.height = height;
          generateGrid();
        });
      });
    });
  })(jQuery);
  