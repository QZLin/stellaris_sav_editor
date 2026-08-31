// Use IIFE to avoid variable conflicts
(function() {
  var origFetch = window.fetch;
  window.fetch = async function(u, o) {
    if (u.includes('api/upload')) {
      return new Response(JSON.stringify({
        success:true, filename:'t.sav',
        meta:{version:'Caelum v3.9.1',name:'Test Empire',date:'2341.07.01',ironman:false,dlcs:['Utopia'],meta_fleets:10,meta_planets:5},
        player_country_id:'0', gamestate_size:100000
      }), {status:200, headers:{'Content-Type':'application/json'}});
    }
    if (u.includes('api/stats')) {
      return new Response(JSON.stringify({
        date:'2341.07.01',tick:4,num_species:50,num_countries:10,
        player_country_id:'0',tech_count:100,fleet_size:20,
        military_power:15000,empire_size:500,owned_planets_count:5
      }), {status:200, headers:{'Content-Type':'application/json'}});
    }
    if (u.includes('api/countries')) {
      return new Response(JSON.stringify({
        countries:[
          {id:'0',name:'Test Empire',type:'default',custom_name:true,capital:0,military_power:15000,economy_power:8000,tech_power:20000,fleet_size:20},
          {id:'1',name:'Alien Empire',type:'default',custom_name:false,capital:5,military_power:8000,economy_power:5000,tech_power:10000,fleet_size:10}
        ],
        player_country_id:'0'
      }), {status:200, headers:{'Content-Type':'application/json'}});
    }
    if (u.includes('api/resources')) {
      var res = {
        energy:{value:5000,label:'能量币',icon:'Z',income:200},
        minerals:{value:3000,label:'矿物',icon:'G',income:150},
        food:{value:2000,label:'食物',icon:'W',income:100},
        physics_research:{value:500,label:'物理学研究',icon:'F',income:50},
        society_research:{value:400,label:'社会学研究',icon:'D',income:40},
        engineering_research:{value:600,label:'工程学研究',icon:'C',income:60},
        influence:{value:100,label:'影响力',icon:'CR',income:5},
        unity:{value:800,label:'凝聚力',icon:'SP',income:30},
        consumer_goods:{value:1500,label:'消费品',icon:'M',income:80},
        alloys:{value:500,label:'合金',icon:'WR',income:40}
      };
      return new Response(JSON.stringify({
        resources:res, country_id:'0',
        categories:{'基础资源':['energy','minerals','food'],'科研':['physics_research','society_research','engineering_research'],'战略资源':['influence','unity','consumer_goods','alloys']}
      }), {status:200, headers:{'Content-Type':'application/json'}});
    }
    if (u.includes('api/species')) {
      return new Response(JSON.stringify({
        species:[
          {id:'1',name:'人类',class:'HUM',portrait:'human',traits:['trait_intelligent','trait_adaptive'],home_planet:0},
          {id:'2',name:'机甲人',class:'MACHINE',portrait:'robot',traits:['trait_machine_unit'],home_planet:5}
        ],
        total:50
      }), {status:200, headers:{'Content-Type':'application/json'}});
    }
    return origFetch(u, o);
  };

  var fileInp = document.querySelector('input[type=file]');
  var transfer = new DataTransfer();
  transfer.items.add(new File(['x'], 'test.sav', {type:'application/octet-stream'}));
  fileInp.files = transfer.files;
  fileInp.dispatchEvent(new Event('change', {bubbles: true}));
})();
