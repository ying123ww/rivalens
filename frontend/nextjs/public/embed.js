(function () {
    window.ResearchEngine = {
        init: function () {
            const parentApiUrl = localStorage.getItem("RIVALENS_API_URL");

            // Create container
            const container = document.createElement("div");
            container.id = "rivalens-container";
            container.style.width = "100%";
            container.style.height = "100vh";
            container.style.overflow = "hidden"; // Hide scrollbar

            // Create iframe
            const iframe = document.createElement("iframe");
            iframe.src = "https://rivalens.local" + (parentApiUrl ? "?RIVALENS_API_URL=" + parentApiUrl : "");
            iframe.style.width = "100%";
            iframe.style.border = "none";
            iframe.style.height = "100%";
            iframe.style.overflow = "hidden";

            // Add custom styles to hide scrollbars
            const style = document.createElement("style");
            style.textContent = `
                #rivalens-container {
                    -ms-overflow-style: none;  /* IE and Edge */
                    scrollbar-width: none;     /* Firefox */
                }
                #rivalens-container::-webkit-scrollbar {
                    display: none;             /* Chrome, Safari and Opera */
                }
                #rivalens-container iframe {
                    -ms-overflow-style: none;
                    scrollbar-width: none;
                }
                #rivalens-container iframe::-webkit-scrollbar {
                    display: none;
                }
            `;
            document.head.appendChild(style);

            // Add iframe to container
            container.appendChild(iframe);
            document.currentScript.parentNode.insertBefore(container, document.currentScript);

            // Handle resize
            window.addEventListener("resize", () => {
                iframe.style.height = "100%";
            });

            // Ensure height is set after iframe loads
            iframe.addEventListener("load", () => {
                iframe.style.height = "100%";
            });
        },

        configure: function (options = {}) {
            if (options.height) {
                const iframe = document.querySelector("#rivalens-container iframe");
                if (iframe) {
                    iframe.style.height = options.height + "px";
                }
            }
        },
    };

    // Initialize when script loads
    window.ResearchEngine.init();
})();