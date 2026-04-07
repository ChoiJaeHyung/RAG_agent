/*********************************************************************
*   화일명:main.js
*   EICN 에서 제공하는 전화 이벤트 연동 javascript
*********************************************************************/
var PhoneNum="";
var PhonePeer="";
var UserName="";
var PhoneStatus = "";
var FORWARD_WHEN = "";
var FORWARD_NUM = "";
var MemberStatus = "";

//UI 연동
$(document).ready(function() {

	//처음엔 로그아웃 버튼을 숨김
	$("#logout_btn").hide();

        //로긴버튼
        $("#login_btn").click(function(){
		login();
        });
        //로그아웃버튼
        $("#logout_btn").click(function(){
		logout();
        });

	//상태변경버튼 시작
        $("#memberstatus0").click(function(){
		command_memberstatus('0');
        });
        $("#memberstatus1").click(function(){
		alert("상담중 상태는 콘트롤할수 없음");
		//command_memberstatus('1');
        });
        $("#memberstatus2").click(function(){
		command_memberstatus('2');
        });
        $("#memberstatus3").click(function(){
		command_memberstatus('3');
        });
        $("#memberstatus4").click(function(){
		command_memberstatus('4');
        });
	//상태변경버튼 끝

	//전화걸기버튼
        $("#dial_btn").click(function(){
		click2call();
        });
	//전화받기버튼
        $("#receive_btn").click(function(){
		command_receive();
        });
	//전화끊기버튼
        $("#hangup_btn").click(function(){
		command_hangup();
        });
	//당겨받기버튼
        $("#pickup_btn").click(function(){
		command_pickup();
        });
/*
	//당겨받기버튼1-번호보이게 전화기에서
        $("#pickup_btn1").click(function(){
		command_pickup1();
        });
*/
	//돌려주기버튼-어텐디드
        $("#attended_btn").click(function(){
		command_attended();
        });
	//돌려주기버튼-블라인드
        $("#redirect_btn").click(function(){
		command_redirect();
        });
	//돌려주기 전화끊기버튼
        $("#attended_hangup_btn").click(function(){
		command_attended_hangup();
        });
	//돌려주기버튼-외부어텐디드
        $("#attendedout_btn").click(function(){
		command_attended_out();
        });
	//돌려주기버튼-외부어텐디드
        $("#redirectout_btn").click(function(){
		command_redirect_out();
        });
	//돌려주기버튼-블라인드
        $("#redirecthunt_btn").click(function(){
		command_redirecthunt();
        });
	//착신전환버튼
        $("#forward_btn").click(function(){
		command_forwarding();
        });
	//부분녹취시작
        $("#srec_btn").click(function(){
		command_rec('start');
        });
	//부분녹취종료
        $("#erec_btn").click(function(){
		command_rec('stop');
        });
});
function login()
{
        var userid=$("#userid").val();
        var exten=$("#exten").val();
        var passwd=$("#passwd").val();
        var company_id=$("#company_id").val();
        if(company_id == "" || userid == "" || exten=="" || passwd == "")
        {
                alert("로긴 정보를 모두 입력하세요");
                return;
        }
        var server_ip = $("#server_ip").val(); 
        //패스워드암호화
        passwd=hex_sha512(passwd);


        if(server_ip !='')
        {
                var nodejs_connector_url = "https://cloudlite.uplus.co.kr:8087/";
                //소켓프레임으로 IPCC서버 로긴을 요청함
                socket_frame.ConnectServer(nodejs_connector_url,company_id,userid,exten,passwd,server_ip,"M","0");
        } else {
                return;
        }
}
function remove_box()
{
        event_num=0;
        $("#snd_text").val("");
}
//------------서버로 명령어보내기 ------------
function SendCommand(strCommand)
{
        if(PhoneNum == null || PhoneNum == "")
        {
                alert("로긴후 사용해주세요");
                return false;
        }
        var cmd = "";
        if(strCommand == 'Bye.')
        {
                cmd = strCommand;
        } else {
                cmd = "CMD|"+strCommand;
        }
        //소켓프레임으로 명령어 전달
        socket_frame.SendCommand2Socket(cmd);
        return false;
}
 
//-------------클릭투콜----------
function click2call()
{
	var number = $("#number");
	var cid_num = $("#cid");
	if(number.length == 0 || number.val() == "")
	{
		alert("전화번호를 입력하세요");
		return;
	}
        alert(number.val()+"로 전화걸기");
	num = number.val();
	cid = cid_num.val();
	SendCommand("CLICKDIAL|"+cid+","+num+",oubbound");
        return false;
}
//----------버튼 콘트롤------------
function changeLogout()
{
	var login_div = $("#LOGIN_DIV");
	if(login_div.length==0)
	{
		return;
	}
	//로긴버튼은 감추고 로그아웃버튼을 보여줌
	$("#login_btn").hide();
	$("#logout_btn").show();
	login_div.html( "<img src='left_dot01.gif'> <b>[상담원:"+UserName+"/"+PhoneNum+"/"+PhonePeer+"]</b>");

	var status_div = $("#STATUS_DIV");
	if(status_div.length>0)
	{
		status_div.show();
	}

	parseForwarding(FORWARD_NUM,FORWARD_WHEN);
	parsePhoneStatus(PhoneStatus);
	parseMemberStatus(MemberStatus);
	parseRecordType(RECORD_TYPE);
}
 
<!------------MESSAGE PARSE START------------>
 
//로긴
function parseLogin(kind,data1,data2,data3,data4, data5,data6,data7,data8)
{
        //LOGIN|KIND:LOGIN_OK|DATA1:300|DATA2:상담원1|DATA3:0|DATA4:OK|DATA5:11110002
        if(kind == "LOGIN_OK")
        {
                PhoneNum=data1;
                PhonePeer=data5;
                UserName=data2;
                MemberStatus = data3;
                PhoneStatus = data4;
                FORWARD_WHEN = data6;
                FORWARD_NUM = data7;
                RECORD_TYPE = data8;

		SendCommand("LOGIN_ACK");
		setTimeout("changeLogout()",1000);
 
        } else if(kind == "LOGOUT"){
                alert("로그아웃");
        } else {
                alert("로긴 실패");
        }
        return;
}
function parseCallStatus(kind,data1,data2)
{
        if(kind == "REDIRECT")
        {
                if(data2 == "NOCHAN")
                {
                        //alert("돌려주기할 채널이 없음");
                        return;
                } else if(data2 == "BUSY") {
                        //alert(data1+"이 통화중");
                        return;
                }
        }
}
function parseCallEvent(kind,data1,data2,data3,data4,data5,data6)
{
/*
        if(kind == "IR")
        {
                alert("**"+PhoneNum+" 인바운드 전화가 ["+data1+"]에서 왔음");
        } else if(kind == "ID") {
                alert("**"+PhoneNum+" 인바운드 전화 ["+data1+"]와 통화중");
        } else if(kind == "OR") {
                alert("**"+PhoneNum+" 아웃바운드 전화 ["+data1+"]와 시도중");
        } else if(kind == "OD") {
                alert("**"+PhoneNum+" 아웃바운드 전화 ["+data1+"]와 통화중");
        } else if(kind == "PICKUP") {
                alert("**"+PhoneNum+" 당겨받기 전화 ["+data1+"]와 통화중");
        }
*/
}
 
function parseHangupEvent(kind,data1,data2,data3,data4)
{
        //alert("**"+PhoneNum+" 전화끊음 ["+data1+","+data2+"]");
}
function parseDTMFRead(kind)
{
	 $("#dtmf_num").val($("#dtmf_num").val()+kind);
}
function parseMemberStatus(kind)
{
        MemberStatus = kind;
        var memberstatus0 = $("#memberstatus0");
        var memberstatus1 = $("#memberstatus1");
        var memberstatus2 = $("#memberstatus2");
        var memberstatus3 = $("#memberstatus3");
        var memberstatus4 = $("#memberstatus4");

        if(kind =='0')
        {
                if(memberstatus0.length>0){memberstatus0.css("backgroundColor","red")};
                if(memberstatus1.length>0){memberstatus1.css("backgroundColor","white")};
                if(memberstatus2.length>0){memberstatus2.css("backgroundColor","white")};
                if(memberstatus3.length>0){memberstatus3.css("backgroundColor","white")};
                if(memberstatus4.length>0){memberstatus4.css("backgroundColor","white")};
        } else if(kind =='1') {
                if(memberstatus0.length>0){memberstatus0.css("backgroundColor","white")};
                if(memberstatus1.length>0){memberstatus1.css("backgroundColor","red")};
                if(memberstatus2.length>0){memberstatus2.css("backgroundColor","white")};
                if(memberstatus3.length>0){memberstatus3.css("backgroundColor","white")};
                if(memberstatus4.length>0){memberstatus4.css("backgroundColor","white")};
        } else if(kind =='2') {
                if(memberstatus0.length>0){memberstatus0.css("backgroundColor","white")};
                if(memberstatus1.length>0){memberstatus1.css("backgroundColor","white")};
                if(memberstatus2.length>0){memberstatus2.css("backgroundColor","red")};
                if(memberstatus3.length>0){memberstatus3.css("backgroundColor","white")};
                if(memberstatus4.length>0){memberstatus4.css("backgroundColor","white")};
        } else if(kind =='3') {
                if(memberstatus0.length>0){memberstatus0.css("backgroundColor","white")};
                if(memberstatus1.length>0){memberstatus1.css("backgroundColor","white")};
                if(memberstatus2.length>0){memberstatus2.css("backgroundColor","white")};
                if(memberstatus3.length>0){memberstatus3.css("backgroundColor","red")};
                if(memberstatus4.length>0){memberstatus4.css("backgroundColor","white")};
        } else if(kind =='4') {
                if(memberstatus0.length>0){memberstatus0.css("backgroundColor","white")};
                if(memberstatus1.length>0){memberstatus1.css("backgroundColor","white")};
                if(memberstatus2.length>0){memberstatus2.css("backgroundColor","white")};
                if(memberstatus3.length>0){memberstatus3.css("backgroundColor","white")};
                if(memberstatus4.length>0){memberstatus4.css("backgroundColor","red")};
        }
}
function parseRecordType(type)
{
	var label = "녹취형태:";
	if(type == '')
	{
		return;
	}
	var rec = $("#record_type");
	if(rec.length>0)
	{
		if(type == 'M')
		{
			rec.html(label+"전수녹취");
		} else if(type == 'P') {
			rec.html(label+"부분녹취");
		}
	}
}
function parseForwarding(num, when)
{
	var label = "착신전환상태:";
	if(when == '')
	{
		when="N";
	}
	var forwarding = $("#forwarding");
	if(forwarding.length>0)
	{
		forwarding.val(num);
	}
	var forward_when = $('#forward_when');
	if(forward_when.length>0)
	{
		$("input[name=forward_when]").each(function(){
			if($(this).val() == when)
			{
				$(this).attr("checked", true);
			}
		});
	}
	if(when == 'A')
	{
		label = label+"항상["+num+"]";
               	$("#forwardstatus").css("background","yellow");
	} else if(when == 'B') {
		label = label+"통화중["+num+"]";
               	$("#forwardstatus").css("background","yellow");
	} else if(when == 'C') {
		label = label+"부재중["+num+"]";
               	$("#forwardstatus").css("background","yellow");
	} else if(when == 'T') {
		label = label+"부재중+통화중["+num+"]";
               	$("#forwardstatus").css("background","yellow");
	} else {
		label = label+"안함";
               	$("#forwardstatus").css("background","white");
	}
	var forwardstatus = $("#forwardstatus");
	if(forwardstatus.length>0)
	{
		forwardstatus.html(label);
	}
}
function parsePhoneStatus(kind)
{
	var phonestatus = $("#phonestatus");
	if(phonestatus.length ==0)
	{
		return;
	}
        if(kind =='OK' || kind =='REGISTERED' ||kind =='REACHABLE' )
        {
                phonestatus.css("background","lightgreen");
        } else if(kind =='NOK' || kind=='UNREACHABLE' || kind=='UNREGISTERED') {
                phonestatus.css("background","gray");
        } else {
                phonestatus.css("background","white");
        }
}
//UI연동////////////////////////////////////////////////////////////////////////////

function logout()
{
	var rtn = confirm("로그아웃하시겠습니까?");

	if(rtn == true)
	{
		SendCommand("Bye.");
	}
        return false;
}
function logoutfromserver()
{
        location.reload();
}
//내선-어텐디드 
function command_attended()
{
        if($("#transfer_num").val() == "")
        {
                alert("돌려줄 상담원의 내선을 입력하세요");
                return;
        } else {
                var rtn = confirm("["+$("#transfer_num").val()+"] 로 전화를 돌리시겠습니까?");
 
                if(rtn == false)
                {
                        return;
                }
        }
        SendCommand("ATTENDED|"+$("#transfer_num").val());
        return false;
}
//내선-블라인드 
function command_redirect()
{
        if($("#transfer_num").val()=="")
        {
                alert("돌려줄 상담원의 내선을 입력하세요");
                return;
        } else {
                var rtn = confirm("["+$("#transfer_num").val()+"] 로 전화를 돌리시겠습니까?");
 
                if(rtn == false)
                {
                        return;
                }
        }
        SendCommand("REDIRECT|"+$("#transfer_num").val());
        return false;
}
//내선-블라인드 
function command_redirecthunt()
{
        if($("#redirecthunt_num").val()=="")
        {
                alert("돌려줄 번호(헌트,대표)를 입력하세요");
                return;
        } else {
                var rtn = confirm("["+$("#redirecthunt_num").val()+"] 로 전화를 돌리시겠습니까?");
 
                if(rtn == false)
                {
                        return;
                }
        }
        SendCommand("REDIRECT_HUNT|"+$("#redirecthunt_num").val());
        return false;
}
//외부-어텐디드 
function command_attended_out()
{
        if($("#transferout_num").val() == "")
        {
                alert("돌려줄 번호를 입력하세요");
                return;
        } else {
                var rtn = confirm("["+$("#transferout_num").val()+"] 로 전화를 돌리시겠습니까?");
 
                if(rtn == false)
                {
                        return;
                }
        }
        SendCommand("ATTENDED_OUT|"+$("#transferout_num").val());
        return false;
}
//외부-블라인드 
function command_redirect_out()
{
        if($("#transferout_num").val() == "")
        {
                alert("돌려줄 번호를 입력하세요");
                return;
        } else {
                var rtn = confirm("["+$("#transferout_num").val()+"] 로 전화를 돌리시겠습니까?");
 
                if(rtn == false)
                {
                        return;
                }
        }
        SendCommand("REDIRECT_OUT|"+$("#transferout_num").val());
        return false;
}
function command_rec(mode)
{
	if(mode == 'start')
	{
        	SendCommand("REC_START|"+PhonePeer);
	} else {
        	SendCommand("REC_STOP|"+PhonePeer);
	}
        return false;
}
function command_memberstatus(s)
{
        SendCommand("MEMBERSTATUS|"+s+","+PhoneNum+","+MemberStatus);
}
function command_hangup()
{
        SendCommand("HANGUP|"+PhonePeer);
}
function command_attended_hangup(){
	SendCommand( "ATTENDEDHANGUP|"+PhonePeer );
}
function command_receive()
{
        SendCommand("RECEIVE|"+PhonePeer);
}
function command_reject()
{
        SendCommand("REJECT|"+PhonePeer);
}
function command_pickup()
{
        SendCommand("PICKUP|"+PhonePeer);
}
function selectForward(value)
{
	FORWARD_WHEN = value;
}
function command_forwarding()
{
	if(FORWARD_WHEN != 'N' && $("#forwarding").val()=='')
	{
		alert("착신전환할 번호를 입력해주세요");
		return;
	}
        SendCommand("FORWARDING|"+PhoneNum+","+$("#forwarding").val()+","+FORWARD_WHEN);
}
function command_multi_end()
{
	if($("#clickmulti_num1").val()=='' && $("#clickmulti_num2").val()=='')
	{
		alert("삼자통화할 내선 번호를 입력해주세요");
		return;
	}
        SendCommand("MULTIDIAL_END|"+PhoneNum);
}

