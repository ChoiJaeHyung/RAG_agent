/*********************************************************************
*   socket_frame.js
*********************************************************************/
var event_num=0;
var socket = null;
var B_MEMBER_STATUS = "0";
var C_MEMBER_STATUS = "0";

$(window).bind('beforeunload', function(){
	if(socket != null)
	{
        	SendCommand2Socket("Bye.");
		alert("상담원 어플리케이션이 정상적으로 로그아웃되었습니다.");
	}
});

$(document).ready(function() {
        //비우기버튼
        $("#remove_btn").click(function(){
                remove_box();
        });
});
function remove_box()
{
        event_num=0;
        $("#snd_text").val("");
}
//------------서버연동 ------------
function ConnectServer(nodejs_connector_url,company_id,userid,exten,passwd,server_ip,usertype,option)
{
	displayText("S", "로긴정보보내기("+company_id+","+userid+","+passwd+")");
try{
        socket = io.connect(nodejs_connector_url, {
                'secure' : true,
                'reconnect' : true,
                'resource' : 'socket.io'
        });
        socket.emit('climsg_login', {
                company_id : company_id,
                userid : userid,
                exten : exten,
                passwd : passwd,
                serverip : server_ip,
                usertype : usertype,
                option : option
        });
        socket.on('connect', function() {
                parseMessage("NODEJS|KIND:CONNECT_OK");
        });
        socket.on('svcmsg', function(data) {
                parseMessage(data);
        });
        socket.on('svcmsg_ping', function() {
                socket.emit('climsg_pong');
        });
        socket.on('disconnect', function() {
                parseMessage("NODESVC_STATUS|KIND:DISCONNECT");
        });
        socket.on('error', function() {
                parseMessage("NODESVC_STATUS|KIND:ERROR");
        });
        socket.on('end', function() {
                parseMessage("NODESVC_STATUS|KIND:END");
        });
        socket.on('close', function() {
                parseMessage("NODESVC_STATUS|KIND:CLOSE");
        });
}catch(error){
        alert("서버가 정상인지 확인후 사용해주세요");
}
}
//------------서버로 명령어보내기 ------------
function SendCommand2Socket(strCommand)
{
        if(socket != null)
        {
		displayText("S", strCommand);
                socket.emit('climsg_command',strCommand);
        } else {
                parseMessage("NODESVC_STATUS|KIND:RELOADED");
        }
        return false;
}
<!------------MESSAGE PARSE START------------>
function parseNodeSvc(kind)
{
        alert("Nodejs 서버 장애["+kind+"]");
        parent.logoutfromserver();
}
function parseLogout(kind)
{
        parent.logoutfromserver();
}
function parseBye(kind, uid, name)
{
        alert("["+kind+"]"+name+"("+uid+")");
        parent.logoutfromserver();
}
function parseMessage(msg)
{
	displayText("R", msg);
        var msgs=msg.split("|");
        if(msgs == null || msgs.length < 2)
        {
                return;
        }
        var Insp=new Object();
        var event =msgs[0];
        for(i=1;i<msgs.length;i++)
        {
                var keyval=msgs[i].split(":");
                var tmp_val ="";
                for(j=1;j<keyval.length;j++)
                {
                        if(keyval[j] != null)
                        {
                                if(j>1)
                                {
                                        tmp_val = tmp_val+":"+keyval[j];
                                } else {
                                        tmp_val = tmp_val+keyval[j];
                                }
                        }
                }
                Insp[keyval[0]]=tmp_val;
        }
        var kind = Insp["KIND"];
        var peer = Insp["PEER"];
        var data0 = Insp["DATA0"];
        var data1 = Insp["DATA1"];
        var data2 = Insp["DATA2"];
        var data3 = Insp["DATA3"];
        var data4 = Insp["DATA4"];
        var data5 = Insp["DATA5"];
        var data6 = Insp["DATA6"];
        var data7 = Insp["DATA7"];
        var data8 = Insp["DATA8"];
        var data9 = Insp["DATA9"];
        var data10 = Insp["DATA10"];
        var data11 = Insp["DATA11"];
        var data12 = Insp["DATA12"];

 
 
        if(event == "LOGIN")
        {
                parent.parseLogin(kind,data1,data2,data3,data4,data5,data6,data7,data8);
                return;
        } else if(event == "PEER"){
		parent.parsePhoneStatus(data2);
                return;
        } else if(event == "MEMBERSTATUS") {
		if(C_MEMBER_STATUS != "1")
		{
			B_MEMBER_STATUS = C_MEMBER_STATUS;
		}
		C_MEMBER_STATUS = kind;
		parent.parseMemberStatus(kind);
        } else if(event == "CALLEVENT") {
		//내선일때 팝업을 막고 싶다면
                if(data1.length==3 && data2.length==3)
                {
                       	return;
                }

		parent.parseCallEvent(kind,data1,data2,data3,data4,data5,data6,data7,data8,data9,data10,data11,data12);
                return;
        } else if(event == "HANGUPEVENT") {
 
                if(data8 == "" &&  data1.length == 3 && data2.length == 3)//내선끊은후 이전 상태콘트롤
               	{
			data8 = B_MEMBER_STATUS;
               	} else if(data8 == "") {
                        data8 = "NORMAL";
		}
		SendCommand2Socket("CMD|HANGUP_ACK|"+data5+","+data8);
                parent.parseHangupEvent(kind,data1,data2,data3,data4,data7,data8,data9,data10,data11);
                return;
        } else if(event == "RECORDSTATUS") {
                parent.parsePartRecord(kind,data1,data2);
        } else if(event == "CALLBACKEVENT") {
		parent.parseCallbackCnt(data1,'evet');
                return;
        } else if(event == "MULTICHANNEL") {
		parent.parseMultiCnt(data1,'event');
                return;
        } else if(event == "FORWARDING") {
		if(kind == 'OK')
		{
                	//parseForwarding(data1,data2);
		}
                return;
        } else if(event == "CALLSTATUS") {
                parent.parseCallStatus(kind,data1,data2);
                return;
        } else if(event == "DTMFREADEVENT"){
                parent.parseDTMFRead(kind);
        } else if(event == "PDSMEMBERSTATUS") {
                parent.parsePDSMemberStatus(kind);
        } else if(event == "PDS_READY") {
                //parent.parsePDSReady(kind,data1,data2,data3,data4,data5,data6,data7);
                return;
        } else if(event == "PDS_STOP") {
                //parent.parsePDSStop(kind,data1,data2);
                return;
        } else if(event == "PDS_START"){
                //parent.parsePDSStart(kind,data1,data2);
                return;
        } else if(event == "PDS_DELETE") {
                //parent.parsePDSDelete(kind,data1,data2);
                return;
        } else if(event == "PDS_STAT") {
                //parent.parsePDSStat(kind,data1,data2,data3,data4);
                return;
        } else if(event == "PDS_STATUS") {
                //parent.parsePDSStatus(kind,data1,data2,data3);
                return;
        } else if(event == "SERVER_STATUS") {
		parseLogout(kind);
        } else if(event == "NODESVC_STATUS") {
		parseNodeSvc(kind);
        } else if(event == "BYE") {
        	if(kind == "SAME_UID")
	        {
			alert("다른 컴퓨터에서 같은 아이디로 로긴되어서 서버와 끊김");
	        }
	        else if(kind == "SAME_PID")
	        {
			alert("다른 컴퓨터에서 같은 내선으로로 로긴되어서 서버와 끊김");
	        }
		parseBye(kind,data1,data3);
        } else {
                //alert("ELSE:"+msg);
        }
        return;
}

//UI연동////////////////////////////////////////////////////////////////////////////

function displayText(fsend, text)
{
        event_num = event_num+1;
        if(fsend == "S")
        {
                $("#snd_text").val($("#snd_text").val()+"\nC->S["+event_num+"] "+text);
        } else {
                $("#snd_text").val($("#snd_text").val()+"\nS->C["+event_num+"] "+text);
        }
}

