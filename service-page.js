const button=document.querySelector('[data-service]');
if(button){button.href=`index.html?servico=${encodeURIComponent(button.dataset.service)}#contato`;}
