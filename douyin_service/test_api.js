const fetch = require('node-fetch');

async function testApi() {
  console.log('Testing /api/profile endpoint...');
  const res = await fetch('http://localhost:3000/api/profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url: 'https://www.douyin.com/user/MS4wLjABAAAAjcQdE5qtuNIEEk3LDMn2nPWRcQqfN9WlapA2MouG69T5j6sB7LfFIwYDUbsKyhM-',
      count: 20
    })
  });
  
  console.log('Status:', res.status);
  const data = await res.json();
  console.log('Success:', data.success);
  if (data.success) {
    console.log('User Name:', data.data.userInfo.nickname);
    console.log('Videos found:', data.data.videos.length);
  } else {
    console.log('Error:', data.error);
  }
}

testApi();
