document.documentElement.classList.add('site-locked');
const apiConfig=document.createElement('script');
apiConfig.src='api-config.js';
apiConfig.onload=()=>{const lock=document.createElement('script');lock.src='site-lock.js';document.head.appendChild(lock)};
document.head.appendChild(apiConfig);
const button=document.querySelector('[data-service]');
if(button){button.href=`index.html?servico=${encodeURIComponent(button.dataset.service)}#contato`;}
