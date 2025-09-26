
// Auto-refresh suave sem recarregar página completa
(function() {
    let lastUpdateTime = null;
    let refreshInterval = 30000; // 30 segundos
    
    function updateData() {
        // Verificar se a página ainda está ativa
        if (!document.hidden) {
            fetch(window.location.href + '?refresh=true', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Cache-Control': 'no-cache'
                },
                body: JSON.stringify({
                    action: 'update_data',
                    timestamp: Date.now()
                })
            }).then(response => {
                if (response.ok) {
                    // Atualizar apenas elementos específicos sem recarregar
                    updateMetricsDisplay();
                }
            }).catch(error => {
                console.log('Refresh em background:', error);
            });
        }
    }
    
    function updateMetricsDisplay() {
        // Buscar novos dados e atualizar elementos específicos
        const metricsElements = document.querySelectorAll('[data-testid="metric-container"]');
        metricsElements.forEach(element => {
            // Adicionar efeito visual suave
            element.style.transition = 'opacity 0.3s ease';
            element.style.opacity = '0.7';
            setTimeout(() => {
                element.style.opacity = '1';
            }, 300);
        });
    }
    
    // Iniciar auto-refresh
    setInterval(updateData, refreshInterval);
    
    // Atualizar imediatamente quando a página voltar ao foco
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            updateData();
        }
    });
})();
